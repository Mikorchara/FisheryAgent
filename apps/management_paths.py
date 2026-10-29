"""Management data locations, resolved once by composition; never reads files/secrets."""
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class ManagementPaths:
    monitoring: Path
    knowledge: Path
    settings: Path
    policy_directory: Path
    traces: Path
    data_root: Path | None = None

    @classmethod
    def resolve(cls, workspace, *, data_root=None, user_data=False, environment=None):
        if data_root is not None and user_data:
            raise ValueError('DATA_ROOT_OPTIONS_CONFLICT')
        if user_data:
            environment = os.environ if environment is None else environment
            base = environment.get('LOCALAPPDATA', '')
            if not base or not Path(base).is_absolute():
                raise ValueError('LOCALAPPDATA_REQUIRED')
            data_root = Path(base) / 'FisheryManagement'
        if data_root is None:
            data_root = Path(workspace).resolve() / 'apps/data'
        if data_root is not None:
            root = Path(data_root)
            if not root.is_absolute():
                raise ValueError('DATA_ROOT_MUST_BE_ABSOLUTE')
            # Keep the lexical path: startup must detect links, not resolve past them.
            root = Path(os.path.abspath(root))
            return cls(root/'monitoring.sqlite3', root/'knowledge.sqlite3', root/'settings.json',
                       root/'tool-policies', root/'logs/assistant-traces.jsonl', root)
