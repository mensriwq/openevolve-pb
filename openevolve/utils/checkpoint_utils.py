import os
from pathlib import Path

def get_latest_checkpoint(output_dir):
    """
    Find the latest checkpoint in the output directory based on the modification 
    time of metadata.json inside the checkpoint folder.
    
    Args:
        output_dir (str): Path to the openevolve output directory.
        
    Returns:
        str: Path to the latest checkpoint directory, or None if none found.
    """
    checkpoints_dir = Path(output_dir) / "checkpoints"
    if not checkpoints_dir.exists():
        return None
    
    checkpoints = [
        d for d in checkpoints_dir.iterdir() 
        if d.is_dir() and d.name.startswith("checkpoint_")
    ]
    
    if not checkpoints:
        return None
    
    def get_checkpoint_time(checkpoint_path):
        metadata_path = checkpoint_path / "metadata.json"
        if metadata_path.exists():
            return metadata_path.stat().st_mtime
        # Fallback to directory mtime if metadata.json doesn't exist
        return checkpoint_path.stat().st_mtime

    # Sort by calculated time descending (newest first)
    checkpoints.sort(key=get_checkpoint_time, reverse=True)
    return str(checkpoints[0])
