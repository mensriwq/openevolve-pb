import unittest
import os
import sys
import shutil
import tempfile
from pathlib import Path
from io import StringIO
from unittest.mock import patch

import auto_run

class TestAutoRunDynamic(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.test_dir) / "test_project"
        self.project_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def create_mock_project(self, files_dict):
        for name, content in files_dict.items():
            file_path = self.project_dir / name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

    def test_find_python_project(self):
        self.create_mock_project({
            "initial_program.py": "print('hello')",
            "evaluate.py": "def evaluate(): pass",
            "config.yaml": "language: python"
        })
        
        files = auto_run.find_files(str(self.project_dir))
        self.assertTrue(files['initial'].endswith('initial_program.py'))
        self.assertTrue(files['evaluator'].endswith('evaluate.py'))
        self.assertEqual(files['suffix'], 'py')

    def test_find_cpp_project(self):
        # Test C++ detection via config
        self.create_mock_project({
            "initial_program.cpp": "int main() {}",
            "eval.py": "pass",
            "config.yaml": "language: cpp"
        })
        
        files = auto_run.find_files(str(self.project_dir))
        self.assertTrue(files['initial'].endswith('initial_program.cpp'))
        self.assertEqual(files['suffix'], 'cpp')

    def test_config_priority(self):
        # config.yaml should take priority over other .yaml files
        self.create_mock_project({
            "initial_program.py": "pass",
            "evaluate.py": "pass",
            "other.yaml": "key: value",
            "config.yaml": "language: python"
        })
        
        files = auto_run.find_files(str(self.project_dir))
        self.assertTrue(files['config'].endswith('config.yaml'))

    def test_dynamic_output_dir_from_config_name(self):
        # Verify output dir is set based on config-XXX.yaml pattern
        self.create_mock_project({
            "initial_program.py": "pass",
            "evaluate.py": "pass",
            "config-experiment1.yaml": "language: python"
        })
        
        test_args = ['auto_run.py', str(self.project_dir), '--dry-run']
        with patch.object(sys, 'argv', test_args):
            with patch('sys.stdout', new=StringIO()) as fake_out:
                try:
                    auto_run.main()
                except SystemExit: pass
                
                output = fake_out.getvalue()
                # Should detect config-experiment1.yaml and set output to openevolve_output-experiment1
                self.assertIn("openevolve_output-experiment1", output)

    def test_symlink_config_handling(self):
        # Setup a real symlink if possible (skipping on systems that don't support it)
        target_config = self.project_dir / "config-v1.yaml"
        target_config.write_text("language: python")
        
        link_config = self.project_dir / "config.yaml"
        try:
            os.symlink(target_config.name, link_config)
        except OSError:
            self.skipTest("Symlinks not supported")

        self.create_mock_project({
            "initial_program.py": "pass",
            "evaluate.py": "pass"
        })
        
        test_args = ['auto_run.py', str(self.project_dir), '--dry-run']
        with patch.object(sys, 'argv', test_args):
            with patch('sys.stdout', new=StringIO()) as fake_out:
                try:
                    auto_run.main()
                except SystemExit: pass
                
                output = fake_out.getvalue()
                # Should follow symlink to config-v1.yaml and use 'v1' in output path
                self.assertIn("openevolve_output-v1", output)

if __name__ == "__main__":
    unittest.main()
