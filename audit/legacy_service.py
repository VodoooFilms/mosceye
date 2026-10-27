"""Load the immutable pre-fix service so the original audit remains reproducible."""
from pathlib import Path
import importlib.util
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mosceye_legacy',root/'backups/pre-core-2026-10-26/sam_service.py')
service=importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)
service.HERE=root
service.ROOT=root.parent
service.CHECKPOINT=root/'checkpoints/sam_vit_b_01ec64.pth'
