from pathlib import Path
import zipfile


def validate_archive(path):
    with zipfile.ZipFile(path) as package:
        items = package.infolist()
        if len(items) > 10000 or sum(i.file_size for i in items) > 512*1024*1024:
            raise ValueError("Expanded Pack Exceeds Limits")
        seen = set()
        for item in items:
            name = item.filename
            if name.startswith('/') or '..' in Path(name).parts or '\\' in name or ((item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Unsafe ZIP path')
            if name in seen:
                raise ValueError('Duplicate ZIP entry')
            seen.add(name)
        if package.testzip():
            raise ValueError('Corrupt ZIP')



def validate_manifest_package(path, appid):
    """Reject successful HTTP responses that contain another app's package."""
    import re
    validate_archive(path)
    with zipfile.ZipFile(path) as bundle:
        scripts=[item for item in bundle.infolist() if item.filename.lower().endswith('.lua')]
        preferred=[item for item in scripts if Path(item.filename).name==str(appid)+'.lua']
        selected=preferred or scripts
        if len(selected)!=1:raise ValueError("The package must contain exactly one matching Lua script")
        text=bundle.read(selected[0]).decode('utf-8-sig')
        match=re.search(r'(?mi)^\s*addappid\s*\(\s*(\d+)',text)
        if not match or int(match[1])!=int(appid):raise ValueError("Bundle from another AppID")
