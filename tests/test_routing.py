import unittest
from unittest.mock import patch

from server import (
    AGENT_ROLES,
    ask_final_editor,
    detect_project_type,
    extract_quality_score,
    get_agent_config,
    get_agent_provider,
    get_model_candidates,
    is_important_request,
    is_lunch_menu_request,
    normalize_artifacts,
    project_file_contract,
    run_rework_pipeline,
    run_lunch_menu_fast_lane,
    review_focus_for,
    run_role_task,
)


class ProjectRoutingTest(unittest.TestCase):
    def test_detects_macos_swiftui(self):
        self.assertEqual(detect_project_type("SwiftUI로 맥용 지뢰찾기 게임 만들어줘"), "macos_swiftui")
        self.assertEqual(detect_project_type("Xcode에서 여는 macOS 앱"), "macos_swiftui")

    def test_detects_python_cli(self):
        self.assertEqual(detect_project_type("파이썬 CLI 계산기 만들어줘"), "python_cli")

    def test_defaults_to_static_web(self):
        self.assertEqual(detect_project_type("투두리스트 앱 만들어줘"), "web_static")

    def test_swift_contract_does_not_request_html(self):
        contract = project_file_contract("macos_swiftui")
        self.assertIn("Package.swift", contract)
        self.assertIn("main.swift", contract)
        self.assertIn("HTML/CSS/JS가 아니라", contract)

    def test_prompt_package_files_are_normalized(self):
        _, files = normalize_artifacts(
            {
                "brief": "brief",
                "plan": "plan",
                "design": "design",
                "dev": "dev",
                "review": "review",
                "final": "final",
                "files": [
                    {"path": "generated_prompt/codex_prompt.md", "content": "# Prompt"},
                    {"path": "generated_prompt/quality_score.md", "content": "Total: 88/100"},
                    {"path": "../bad.md", "content": "safe path"},
                ],
            }
        )
        self.assertEqual(files[0]["path"], "generated_prompt/codex_prompt.md")
        self.assertEqual(files[1]["path"], "generated_prompt/quality_score.md")
        self.assertEqual(files[2]["path"], "bad.md")

    def test_prompt_contract_mentions_codex_outputs(self):
        contract = project_file_contract("web_static")
        self.assertIn("Codex가 만들 결과물", contract)
        self.assertIn("앱 코드를 직접 납품하지 말고", contract)

    def test_agent_chat_roles_include_dx_and_red_team(self):
        self.assertEqual(AGENT_ROLES["dana"]["role"], "Developer Experience")
        self.assertIn("실패 가능성", AGENT_ROLES["jason"]["prompt"])

    def test_extracts_quality_score_from_prompt_package(self):
        score = extract_quality_score(
            [{"path": "generated_prompt/quality_score.md", "content": "Total: 91/100\nGood"}],
            {},
        )
        self.assertEqual(score["score"], 91)

    def test_model_candidates_include_primary_first(self):
        candidates = get_model_candidates("gemini-2.5-flash-lite")
        self.assertEqual(candidates[0], "gemini-2.5-flash-lite")

    def test_ollama_model_candidates_include_local_fallbacks(self):
        candidates = get_model_candidates("qwen3:14b", "ollama")
        self.assertEqual(candidates[0], "qwen3:14b")
        self.assertIn("qwen2.5-coder:14b", candidates)

    def test_agent_provider_defaults_to_global_provider(self):
        self.assertIn(get_agent_provider("unknown"), ("gemini", "openai", "ollama"))

    def test_important_request_escalates_to_director(self):
        self.assertTrue(is_important_request("신중하게 SwiftUI macOS 앱 프롬프트를 만들어줘"))
        self.assertFalse(is_important_request("간단한 투두 앱 프롬프트 만들어줘"))

    def test_agent_config_exposes_finalizer_fallbacks(self):
        config = get_agent_config()
        self.assertIn("agents", config)
        self.assertIn("finalizer", config)
        self.assertIn("gemini/gemini-2.5-flash", config["finalizer"]["important"])
        self.assertIn("ollama/qwen3:14b", config["finalizer"]["normal"])

    def test_normal_finalizer_skips_director_model(self):
        calls = []

        def fake_ask(*args):
            calls.append((args[4], args[5]))
            return "final"

        with patch("server.ask_agent_once", side_effect=fake_ask):
            answer, route = ask_final_editor(None, "role", "prompt", important=False)

        self.assertEqual(answer, "final")
        self.assertNotIn("gemini-2.5-flash", route)
        self.assertEqual(calls[0], ("gemini-2.0-flash", "gemini"))

    def test_important_finalizer_falls_back_to_local_model(self):
        calls = []

        def fake_ask(*args):
            calls.append((args[4], args[5]))
            if args[5] == "ollama":
                return "local final"
            raise RuntimeError("503 UNAVAILABLE")

        with patch("server.ask_agent_once", side_effect=fake_ask):
            answer, route = ask_final_editor(None, "role", "prompt", important=True)

        self.assertEqual(answer, "local final")
        self.assertEqual(
            calls,
            [
                ("gemini-2.5-flash", "gemini"),
                ("gemini-2.0-flash", "gemini"),
                ("qwen3:14b", "ollama"),
            ],
        )
        self.assertEqual(route, "gemini/gemini-2.5-flash -> gemini/gemini-2.0-flash -> ollama/qwen3:14b")

    def test_role_absence_uses_backup_agent(self):
        performance = []
        calls = []

        def fake_ask(_client, agent_name, *_args):
            calls.append(agent_name)
            if agent_name == "Mike":
                raise RuntimeError("vacation")
            return "Nora handled it"

        with patch("server.ask_agent", side_effect=fake_ask):
            result = run_role_task(None, "pm", "PM / 기획", "role", "prompt", "request", performance)

        self.assertEqual(result, "Nora handled it")
        self.assertEqual(calls[:2], ["Mike", "Nora"])
        self.assertEqual(performance[0]["status"], "결근")
        self.assertEqual(performance[1]["status"], "대체 성공")

    def test_role_absence_keeps_company_running_with_emergency_output(self):
        performance = []

        with patch("server.ask_agent", side_effect=RuntimeError("all out")):
            result = run_role_task(None, "dev", "Dev / 구현안", "role", "prompt", "request", performance)

        self.assertIn("Emergency Dev / 구현안 Output", result)
        self.assertEqual(performance[-1]["status"], "비상 운영")

    def test_artifact_review_focus_is_role_specific(self):
        self.assertIn("위험", review_focus_for("jason"))
        self.assertIn("보안", review_focus_for("sana"))
        self.assertIn("100점", review_focus_for("vera"))
        self.assertIn("실행 방법", review_focus_for("dana"))
        self.assertIn("Swift", review_focus_for("jay"))

    def test_lunch_menu_request_uses_fast_lane(self):
        request = "점심 메뉴 랜덤으로 선택하는 웹앱 만들어줘"
        self.assertTrue(is_lunch_menu_request(request))
        artifacts, files, calls, model = run_lunch_menu_fast_lane(request)
        self.assertEqual(calls, 0)
        self.assertIn("FastLane", model)
        self.assertIn("100개 이상", artifacts["final"])
        self.assertIn("재선택 3번", artifacts["final"])
        self.assertTrue(any(item["path"] == "generated_prompt/codex_prompt.md" for item in files))

    def test_rework_pipeline_generates_rework_prompt(self):
        def fake_review(agent_key, artifact_name, artifact, instruction):
            return {
                "ok": True,
                "agent": agent_key,
                "name": agent_key,
                "role": "test",
                "provider": "ollama",
                "model": "fake",
                "artifact": artifact_name,
                "focus": "test",
                "answer": f"{agent_key} reviewed {instruction}",
            }

        with patch("server.run_artifact_review", side_effect=fake_review):
            result = run_rework_pipeline("점심 앱", "재선택이 4번 됩니다.", "브라우저 확인")

        self.assertEqual(result["mode"], "rework")
        self.assertIn("generated_prompt/rework_prompt.md", result["files"])
        self.assertIn("Codex 재작업 지시서", result["artifacts"]["final"])
        self.assertIn("재선택이 4번 됩니다.", result["artifacts"]["final"])


if __name__ == "__main__":
    unittest.main()
