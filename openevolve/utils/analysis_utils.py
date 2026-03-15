import os
import json
import random
from typing import Dict, List, Any, Tuple, Optional
import numpy as np
import yaml
from openevolve.utils.checkpoint_utils import get_latest_checkpoint

def analyze_checkpoint(checkpoint_path: str, feature_dimensions: Optional[List[str]] = None, feature_bins: Optional[Any] = None) -> Dict[str, Any]:
    """Analyze a checkpoint directory and return comprehensive analysis data."""
    metadata_path = os.path.join(checkpoint_path, "metadata.json")
    if not os.path.exists(metadata_path):
        return None

    with open(metadata_path, 'r') as f:
        metadata = json.load(f)

    island_feature_maps = metadata.get("island_feature_maps", [])
    programs_dir = os.path.join(checkpoint_path, "programs")
    
    # 1. Collect all valid programs and their metrics
    all_programs = {}
    bin_to_program = {}
    
    # feature_dimensions passed in from outside takes priority
    if feature_dimensions:
        resolved_dims = feature_dimensions
    else:
        # Fallback to metadata
        feature_stats_meta = metadata.get("feature_stats", {})
        resolved_dims = list(feature_stats_meta.keys())

    for island_idx, feature_map in enumerate(island_feature_maps):
        for bin_key, program_id in feature_map.items():
            program_path = os.path.join(programs_dir, f"{program_id}.json")
            if os.path.exists(program_path):
                if program_id not in all_programs:
                    with open(program_path, 'r') as f:
                        prog_data = json.load(f)
                        all_programs[program_id] = prog_data
                
                prog_data = all_programs[program_id]
                score = prog_data.get("metrics", {}).get("combined_score", 0)
                
                if bin_key not in bin_to_program or score > bin_to_program[bin_key]['score']:
                    # Extract numeric coordinates from bin_key
                    coords = [float(c) for c in bin_key.split('-')]
                    
                    # Ensure resolved_dims matches length of coords
                    if not resolved_dims or len(resolved_dims) != len(coords):
                        resolved_dims = [f"dim_{i}" for i in range(len(coords))]
                        
                    bin_to_program[bin_key] = {
                        'id': program_id,
                        'score': score,
                        'code': prog_data.get("code", ""),
                        'island': island_idx,
                        'metrics': prog_data.get("metrics", {}),
                        'coords': coords
                    }

    if not bin_to_program:
        return None

    # 2. Calculate Covariance and Statistics
    scores = []
    feature_values = [] 
    
    for prog in bin_to_program.values():
        scores.append(prog['score'])
        feature_values.append(prog['coords'])
    
    scores_arr = np.array(scores)
    features_arr = np.array(feature_values) 
    num_dims = features_arr.shape[1]
    
    if len(resolved_dims) != num_dims:
        resolved_dims = [f"dim_{i}" for i in range(num_dims)]
    
    correlations_with_score = []
    for i in range(num_dims):
        feat_dim = features_arr[:, i]
        if np.std(feat_dim) == 0:
            correlations_with_score.append(0.0)
        else:
            corr = np.corrcoef(feat_dim, scores_arr)[0, 1]
            correlations_with_score.append(corr)
            
    if num_dims > 1:
        with np.errstate(divide='ignore', invalid='ignore'):
            inter_feature_corr = np.corrcoef(features_arr, rowvar=False)
            if isinstance(inter_feature_corr, np.ndarray):
                inter_feature_corr = np.nan_to_num(inter_feature_corr)
    else:
        inter_feature_corr = np.array([[1.0]])

    # 3. Bin Occupancy
    max_bins_per_dim = []
    for i in range(num_dims):
        dim_name = resolved_dims[i]
        
        # Determine bin count for this dimension
        bins = 10 # Default
        if isinstance(feature_bins, int):
            bins = feature_bins
        elif isinstance(feature_bins, dict) and dim_name in feature_bins:
            bins = feature_bins[dim_name]
        
        seen_max = int(np.max(features_arr[:, i])) if features_arr.size > 0 else 0
        max_bins_per_dim.append(max(bins, seen_max + 1))
        
    total_possible_bins = np.prod(max_bins_per_dim)
    occupancy_ratio = len(bin_to_program) / total_possible_bins if total_possible_bins > 0 else 0
    
    sorted_bins = sorted(bin_to_program.keys(), key=lambda k: bin_to_program[k]['score'], reverse=True)
    top_5_keys = sorted_bins[:5]
    remaining_keys = sorted_bins[5:]
    random_5_keys = random.sample(remaining_keys, min(len(remaining_keys), 5))
    
    return {
        'bin_to_program': bin_to_program,
        'feature_stats': {
            'correlations_with_score': correlations_with_score,
            'inter_feature_corr': inter_feature_corr.tolist() if isinstance(inter_feature_corr, np.ndarray) else [[1.0]],
            'occupancy_ratio': occupancy_ratio,
            'num_dims': num_dims,
            'max_bins_per_dim': max_bins_per_dim,
            'dimension_names': resolved_dims
        },
        'samples': {
            'elites': [bin_to_program[k] for k in top_5_keys],
            'random': [bin_to_program[k] for k in random_5_keys]
        },
        'metadata': metadata
    }

def generate_bottleneck_report(analysis_data: Dict[str, Any], checkpoint_name: str, project_name: str = "Project") -> str:
    """Generate a markdown report for bottleneck analysis using structured evidence."""
    if not analysis_data:
        return "No programs found in bins."

    stats = analysis_data['feature_stats']
    samples = analysis_data['samples']
    dim_names = stats['dimension_names']
    
    report = f"# Evolution Bottleneck Diagnosis: {project_name}\n"
    report += f"**Checkpoint**: `{checkpoint_name}`\n\n"
    
    report += "## 1. Quantitative Evidence (Feature Space Analysis)\n"
    report += "This section analyzes whether the chosen feature dimensions are effectively guiding the evolution or if they have become redundant.\n\n"
    
    report += f"- **MAP-Elites Space Occupancy**: {stats['occupancy_ratio']*100:.2f}% ({len(analysis_data['bin_to_program'])} occupied bins)\n"
    report += f"- **Number of Dimensions**: {stats['num_dims']}\n"
    report += f"- **Dimension Definitions**: `{dim_names}`\n"
    report += f"- **Estimated Bins per Dimension**: {stats['max_bins_per_dim']}\n\n"
    
    report += "### Feature-Score Correlation\n"
    report += "High correlation (approaching ±1.0) indicates that a feature is redundant with the score and provides no independent selection pressure for diversity.\n"
    for i, corr in enumerate(stats['correlations_with_score']):
        name = dim_names[i]
        warning = " ⚠️ **(Redundant)**" if abs(corr) > 0.85 else ""
        report += f"- **{name}**: {corr:.4f}{warning}\n"
    report += "\n"
    
    if stats['num_dims'] > 1:
        report += "### Inter-Feature Correlation Matrix\n"
        report += "High values between dimensions indicate feature redundancy.\n"
        report += "```\n"
        padding = max(len(name) for name in dim_names) + 2
        header = " " * padding + "".join([f"{name:>{padding}}" for name in dim_names])
        report += header + "\n"
        for i, row in enumerate(stats['inter_feature_corr']):
            name = dim_names[i]
            row_str = f"{name:>{padding}}" + "".join([f"{v:>{padding}.2f}" for v in row])
            report += row_str + "\n"
        report += "```\n\n"

    report += "## 2. Qualitative Evidence (Program Behavior Sampling)\n"
    report += "We have sampled 5 top-performing 'Elite' programs and 5 programs from across the rest of the feature space.\n\n"
    
    def format_prog_list(progs, title):
        res = f"### {title}\n"
        for prog in progs:
            coord_str = ", ".join([f"{dim_names[i]}={val}" for i, val in enumerate(prog['coords'])])
            res += f"#### Program `{prog['id'][:8]}` (Bin: [{coord_str}], Score: {prog['score']:.4f})\n"
            res += f"- **Key Metrics**: `{json.dumps(prog['metrics'])}`\n"
            res += "```python\n"
            res += prog['code'] + "\n"
            res += "```\n\n"
        return res

    report += format_prog_list(samples['elites'], "Group A: Top 5 Elites (Performance Ceiling)")
    report += format_prog_list(samples['random'], "Group B: Diverse Samples (Exploration State)")

    report += "## 3. Diagnosis Request\n"
    report += "Based on the evidence above, please perform a deep diagnostic analysis of the current evolution state:\n\n"
    
    report += "### Part A: Feature Dimension Validation\n"
    report += "- Review the correlation data. Are the current feature dimensions 'derelict' (i.e., too highly correlated with the score or with each other)?\n"
    report += "- If a dimension is derelict, it fails to provide the necessary 'behavioral niche' for MAP-Elites. Should it be replaced?\n"
    report += "- If replacement is needed, suggest 2-3 specific new feature dimensions that could better capture structural or behavioral diversity for this specific problem.\n\n"
    
    report += "### Part B: Evolution Stagnation Analysis\n"
    report += "- Compare Group A (Elites) and Group B (Diverse Samples). \n"
    report += "- **Scenario 1**: If Group B programs use the same logic as Group A but with lower scores, the system is 'stuck' in a local optimum. The issue might be insufficient induction of new strategies.\n"
    report += "- **Scenario 2**: If Group B programs are completely broken or score near zero while being logic-less, the feature space might be rewarding 'noise' instead of meaningful behavioral variations.\n"
    report += "- Does the current evolution demonstrate a healthy 'exploration vs. exploitation' balance?\n\n"
    
    report += "### Part C: Strategic Recommendations\n"
    report += "- If the features are fine but progress is stalled, what new 'exploration directions' should the system take?\n"
    report += "- Suggest specific algorithmic techniques or code patterns that haven't appeared in the current top programs but might break the current performance ceiling.\n"
    
    return report

def run_bottleneck_analysis(output_dir: str, project_dir: str, feature_dimensions: Optional[List[str]] = None, feature_bins: Optional[Any] = None):
    """Run the analysis and save it to the project directory."""
    checkpoint_path = get_latest_checkpoint(output_dir)
    if not checkpoint_path:
        print(f"Error: No checkpoint found in {output_dir}")
        return False
    
    # Fallback: analysis tries to read config.yaml itself if dimensions not provided
    if not feature_dimensions:
        config_path = os.path.join(project_dir, "config.yaml")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                    if 'database' in config:
                        feature_dimensions = config['database'].get('feature_dimensions')
                        feature_bins = config['database'].get('feature_bins')
            except:
                pass

    print(f"Analyzing latest Checkpoint: {checkpoint_path}")
    analysis_data = analyze_checkpoint(checkpoint_path, feature_dimensions, feature_bins)
    
    if analysis_data:
        checkpoint_name = os.path.basename(checkpoint_path)
        project_name = os.path.basename(project_dir).replace('_', ' ').title()
        report = generate_bottleneck_report(analysis_data, checkpoint_name, project_name)
        
        output_file = os.path.join(project_dir, "bottleneck_diagnosis.md")
        with open(output_file, 'w') as f:
            f.write(report)
        
        print(f"\nAnalysis complete! Diagnosis evidence generated at: {output_file}")
        return True
    else:
        print("No valid data found in checkpoint.")
        return False
