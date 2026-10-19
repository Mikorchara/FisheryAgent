"""Create a new, allowlisted build staging directory. Never copies runtime data."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ('ai_backend', 'ai_service', 'knowledge', 'monitoring', 'simulator', 'management_web')


def prepare(destination, *, root=ROOT):
    destination = Path(destination).absolute()
    # Build artifacts belong to this workspace until MIG-3 is separately approved.
    if not destination.is_relative_to(root.resolve()/'outputs'):
        raise ValueError('BUILD_STAGE_MUST_BE_UNDER_WORKSPACE_OUTPUTS')
    if any(parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction())
           for parent in (destination, *destination.parents)):
        raise ValueError('BUILD_STAGE_UNSAFE_PATH')
    destination.mkdir(parents=True, exist_ok=False)
    (destination/'apps').mkdir()
    shutil.copyfile(root/'apps/__init__.py', destination/'apps/__init__.py')
    shutil.copyfile(root/'apps/management_paths.py', destination/'apps/management_paths.py')
    for package in PACKAGES:
        source = root/'apps'/package
        for path in sorted(source.rglob('*')):
            relative = path.relative_to(source)
            if any(part in ('tests', '__pycache__', 'development') for part in relative.parts) or not path.is_file():
                continue
            allowed = path.suffix == '.py' or (
                'resources' in relative.parts and path.suffix == '.json') or (
                package == 'management_web' and 'static' in relative.parts and path.suffix in ('.html','.css','.js'))
            if allowed:
                if path.is_symlink():
                    raise ValueError('BUILD_SOURCE_LINK_REFUSED')
                target = destination/'apps'/package/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    shutil.copyfile(root/'scripts/packaging/management.pyproject.toml', destination/'pyproject.toml')
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        prepare(args.destination)
    except (ValueError, OSError) as error:
        parser.error(str(error) if isinstance(error, ValueError) else 'BUILD_STAGE_UNAVAILABLE')
    print('MANAGEMENT_BUILD_STAGE_READY')


if __name__ == '__main__':
    main()
