import unittest

from server import (
    AGENT_ROLES,
    detect_project_type,
    extract_quality_score,
    get_model_candidates,
    normalize_artifacts,
    project_file_contract,
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


if __name__ == "__main__":
    unittest.main()
