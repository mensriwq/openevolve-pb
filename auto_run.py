#!/usr/bin/env python3
import os
import sys
import subprocess
from pathlib import Path
import yaml
import re
import atexit

from openevolve.utils.checkpoint_utils import get_latest_checkpoint
from openevolve.utils.analysis_utils import run_bottleneck_analysis

def find_files(folder_path, override_config=None):
    """Find initial_program, evaluator, and config files in folder"""
    folder = Path(folder_path)
    found = {}

    # 1. Always look for config first to determine language
    if override_config and os.path.exists(override_config):
        found['config'] = override_config
    else:
        # 1.1 config.yaml
        config_path = folder / 'config.yaml'
        if config_path.exists():
            found['config'] = str(config_path)
        else:
            # 1.2 config*.yaml
            config_matches = list(folder.glob('config*.yaml'))
            if config_matches:
                found['config'] = str(config_matches[0])
            else:
                # 1.3 *.yaml
                all_yaml_matches = list(folder.glob('*.yaml'))
                if all_yaml_matches:
                    found['config'] = str(all_yaml_matches[0])
    
    # 2. Check if config is a symlink and get target name
    config_name = None
    if 'config' in found:
        config_full_path = found['config']
        if os.path.islink(config_full_path):
            target = os.readlink(config_full_path)
            config_name = Path(target).name
            print(f"🔗 Config is a symlink, target name: {config_name}")
        else:
            config_name = Path(config_full_path).name

    # 3. Determine language and initial program suffix
    language = 'python'
    program_suffix = None
    if 'config' in found:
        try:
            with open(found['config'], 'r') as f:
                config_data = yaml.safe_load(f)
                language = config_data.get('language', 'python').lower()
                program_suffix = config_data.get('program_suffix', None)
        except:
            pass
    
    # 4. Find initial program based on language/suffix
    if not program_suffix:
        if language in ['cpp', 'c++']:
            program_suffix = '.cpp'
        else:
            program_suffix = '.py'
    
    if not program_suffix.startswith('.'):
        program_suffix = '.' + program_suffix
    
    # Priority: initial_program.suffix -> init*.suffix
    initial_patterns = [f'initial_program{program_suffix}', f'init*{program_suffix}']
    for pattern in initial_patterns:
        matches = list(folder.glob(pattern))
        if matches:
            found['initial'] = str(matches[0])
            break
            
    # 5. Find evaluator (always .py)
    # Priority: evaluate.py -> eval*.py
    evaluator_patterns = ['evaluate.py', 'eval*.py']
    for pattern in evaluator_patterns:
        matches = list(folder.glob(pattern))
        if matches:
            found['evaluator'] = str(matches[0])
            break
    
    found['suffix'] = program_suffix.lstrip('.')
    found['config_name'] = config_name
    return found

def main():
    # Parse only the folder argument and --dry-run, pass everything else through
    if len(sys.argv) < 2 or sys.argv[1] in ['--help', '-h']:
        print("Usage: python auto_run.py <folder> [other openevolve-run.py arguments...]")
        print("\nCustom arguments:")
        print("  --acp         Auto Checkpoint: find the latest checkpoint in the output folder")
        print("  --show        Only run visualizer on the current results")
        print("  --analyze     Run bottleneck analysis on the current results")
        print("  --dry-run     Show the command that would be executed without running it")
        print("\nThis script automatically finds initial_program.py, evaluator.py, and config.yaml")
        print("in the specified folder and passes all other arguments to openevolve-run.py")
        sys.exit(1)
    
    folder = sys.argv[1]
    remaining_args = sys.argv[2:]

    if not os.path.exists(folder):
        print(f"Error: Folder {folder} does not exist")
        sys.exit(1)
    
    # Check for custom arguments in remaining args
    # Robustly check for both --dry-run and --dry_run
    dry_run = '--dry-run' in remaining_args or '--dry_run' in remaining_args
    if '--dry-run' in remaining_args:
        remaining_args.remove('--dry-run')
    if '--dry_run' in remaining_args:
        remaining_args.remove('--dry_run')
    
    show = '--show' in remaining_args
    if show:
        remaining_args.remove('--show')
    
    acp = '--acp' in remaining_args
    if acp:
        remaining_args.remove('--acp')
    
    analyze = '--analyze' in remaining_args
    if analyze:
        remaining_args.remove('--analyze')
    
    # Check if --config is already in remaining args
    user_config_path = None
    for i, arg in enumerate(remaining_args):
        if arg == '--config':
            if i + 1 < len(remaining_args):
                user_config_path = remaining_args[i+1]
            break
        elif arg.startswith('--config='):
            user_config_path = arg.split('=', 1)[1]
            break

    # Find required files
    files = find_files(folder, override_config=user_config_path)
    
    if 'initial' not in files:
        print(f"Error: No initial program found in {folder}")
        sys.exit(1)
    
    if 'evaluator' not in files:
        print(f"Error: No evaluator found in {folder}")
        sys.exit(1)
    
    # Build command with found files
    python_exe = sys.executable if sys.executable else 'python3'
    cmd = [python_exe, 'openevolve-run.py', files['initial'], files['evaluator']]
    
    # Base output folder name
    final_output_dir = os.path.join(folder, "openevolve_output")

    # Add config if found and not already specified in remaining args
    if 'config' in files:
        # Check if --config is already in remaining args
        config_specified = False
        user_config_path = None
        for i, arg in enumerate(remaining_args):
            if arg == '--config':
                config_specified = True
                if i + 1 < len(remaining_args):
                    user_config_path = remaining_args[i+1]
                break
            elif arg.startswith('--config='):
                config_specified = True
                user_config_path = arg.split('=', 1)[1]
                break
        
        if not config_specified:
            cmd.extend(['--config', files['config']])
            user_config_path = files['config']

        # Custom logic for dynamic output folder if config is a symlink or follows config-name.yaml
        config_to_check = user_config_path
        if config_to_check:
            config_filename = os.path.basename(config_to_check)
            
            # If it's a symlink, we prioritize the target's name for naming the output folder
            if os.path.islink(config_to_check):
                target = os.readlink(config_to_check)
                config_filename = os.path.basename(target)
            
            # Match config*.yaml and capture the * part
            match = re.search(r'config(.*)\.yaml', config_filename)
            if match:
                config_extra = match.group(1) # This includes the separator like -name or _name
                
                # Dynamic output folder prefix
                prefix = "openevolve_output"
                
                # Handle suffix suffix (e.g., config-xxx-cpp)
                suffix = files.get('suffix', 'py')
                suffix_tag = f"-{suffix}" if suffix != 'py' else ""
                
                # If the extra part already ends with the suffix tag, don't add it again
                # Normalize separators for check: replace _ with -
                suffix_tag_norm = suffix_tag.replace('_', '-')
                config_extra_norm = config_extra.replace('_', '-')
                
                if suffix_tag and config_extra_norm.endswith(suffix_tag_norm):
                    custom_output = f"{prefix}{config_extra}"
                else:
                    custom_output = f"{prefix}{config_extra}{suffix_tag}"
                
                # Check if user already specified --output
                output_specified = False
                for arg in remaining_args:
                    if arg == '--output' or arg == '-o' or arg.startswith('--output='):
                        output_specified = True
                        break
                
                if not output_specified:
                    full_output_path = os.path.join(folder, custom_output)
                    print(f"📁 Setting dynamic output directory based on config name: {full_output_path}")
                    cmd.extend(['--output', full_output_path])
                    final_output_dir = full_output_path
    
    # Handle show option (skip openevolve-run.py and just run visualizer)
    if show or analyze:
        # We still need final_output_dir, let's look for --output in remaining_args
        for i, arg in enumerate(remaining_args):
            if arg == '--output' or arg == '-o':
                if i + 1 < len(remaining_args):
                    final_output_dir = remaining_args[i+1]
                break
            elif arg.startswith('--output='):
                final_output_dir = arg.split('=', 1)[1]
        
        if show:
            visualizer_cmd = [python_exe, 'scripts/visualizer.py', '--path', final_output_dir]
            print(f"👁️ --show specified. Running visualizer only on: {final_output_dir}")
            print(f"Visualizer command: {' '.join(visualizer_cmd)}")
            
            if dry_run:
                if not analyze: return
            else:
                try:
                    subprocess.run(visualizer_cmd, check=True)
                    if not analyze: return
                except subprocess.CalledProcessError as e:
                    print(f"Error running visualizer: {e}")
                    sys.exit(1)
        
        if analyze:
            print(f"🔍 --analyze specified. Running bottleneck analysis on: {final_output_dir}")
            if dry_run:
                print(f"[DRY RUN] Would run bottleneck analysis on {final_output_dir} for project {folder}")
                return
            
            # Extract dimension info from config if available
            feature_dimensions = None
            feature_bins = None
            if user_config_path and os.path.exists(user_config_path):
                try:
                    with open(user_config_path, 'r') as f:
                        config_data = yaml.safe_load(f)
                        if 'database' in config_data:
                            feature_dimensions = config_data['database'].get('feature_dimensions')
                            feature_bins = config_data['database'].get('feature_bins')
                except:
                    pass

            success = run_bottleneck_analysis(final_output_dir, folder, feature_dimensions, feature_bins)
            if success:
                return
            else:
                sys.exit(1)

    # Handle auto checkpoint (acp)
    if acp:
        # Check if user explicitly specified output directory in remaining_args
        # This overrides any default or symlink-derived output directory
        for i, arg in enumerate(remaining_args):
            if arg == '--output' or arg == '-o':
                if i + 1 < len(remaining_args):
                    final_output_dir = remaining_args[i+1]
                break
            elif arg.startswith('--output='):
                final_output_dir = arg.split('=', 1)[1]
        
        latest_checkpoint = get_latest_checkpoint(final_output_dir)
        if latest_checkpoint:
            print(f"🚩 Found latest checkpoint for --acp: {latest_checkpoint}")
            cmd.extend(['--checkpoint', latest_checkpoint])
        else:
            print(f"⚠️ --acp was specified but no checkpoint was found in {final_output_dir}")

    # Add all remaining arguments as-is
    cmd.extend(remaining_args)
    
    print(f"Found files:")
    for file_type, path in files.items():
        print(f"  {file_type}: {path}")
    
    if remaining_args:
        print(f"\nPassing through arguments: {' '.join(remaining_args)}")
    
    print(f"\nFull command: {' '.join(cmd)}")
    
    if dry_run:
        print("\n[DRY RUN] - Command would be executed but --dry-run was specified")
        return
    
    # Execute
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)

if __name__ == '__main__':
    main()