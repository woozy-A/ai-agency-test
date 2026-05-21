import unittest

from server import detect_project_type, project_file_contract


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
        self.assertIn("HTML/CSS/JS 파일을 만들지 마라", contract)


if __name__ == "__main__":
    unittest.main()
