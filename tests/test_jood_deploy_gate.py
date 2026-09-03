import pathlib
import unittest


class JoodDeployGateTests(unittest.TestCase):
    def test_deploy_loads_production_env_before_import_and_tests(self):
        script = pathlib.Path("deploy/gce/install-ai-company.sh").read_text(encoding="utf-8")
        source_pos = script.index("source /etc/pakgat/pakgat.env")
        import_pos = script.index("import main")
        tests_pos = script.index("test_jood_*.py")
        self.assertLess(source_pos, import_pos)
        self.assertLess(source_pos, tests_pos)

    def test_voice_dependency_is_installed_before_app_import(self):
        script = pathlib.Path("deploy/gce/install-ai-company.sh").read_text(encoding="utf-8")
        install_pos = script.index("edge-tts==7.2.8")
        import_pos = script.index("import main")
        self.assertLess(install_pos, import_pos)


if __name__ == "__main__":
    unittest.main()
