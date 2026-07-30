#!/usr/bin/env python3
"""
Generate integrity manifest for AI Security Guardian.

This script scans all project .py, .yaml, and requirements files,
computes SHA256 hashes, and saves them to integrity_manifest.json.

Run this after:
  - First clone / setup
  - After `git pull` updating the code
  - After `pip install` changing dependencies
  - After any intentional code modification

Usage:
  python generate_integrity_manifest.py              # Generate manifest
  python generate_integrity_manifest.py --verify     # Verify against existing manifest
  python generate_integrity_manifest.py --dry-run    # Show what would be hashed
"""
import sys
from pathlib import Path

# Fix GBK encoding issue on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure parent is on path
sys.path.insert(0, str(Path(__file__).parent))
from agent.self_audit import FileHasher, IntegrityManifest, SelfAuditor


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate integrity manifest for AI Security Guardian",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Verify files against existing manifest (don't generate)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List files that would be hashed without writing manifest",
    )
    args = parser.parse_args()

    root = Path(__file__).parent
    hasher = FileHasher()
    manifest = IntegrityManifest(root / "integrity_manifest.json")

    if args.verify:
        # Verify mode
        if not manifest.load():
            print("❌ No manifest found. Run without --verify to generate one.")
            return 1

        auditor = SelfAuditor(str(root))
        result = auditor.verify_files()

        if result["ok"]:
            print(f"✅ All {result['verified_count']} files verified — integrity intact")
            return 0
        else:
            print("❌ Integrity check FAILED!")
            if result["modified_count"] > 0:
                print(f"\n   Modified files ({result['modified_count']}):")
                for m in result["details"]["modified"]:
                    print(f"   🔴 {m['file']}")
                    print(f"      expected: {m['expected']}")
                    print(f"      actual:   {m['actual']}")
            if result["missing_count"] > 0:
                print(f"\n   Missing files ({result['missing_count']}):")
                for m in result["details"]["missing"]:
                    print(f"   🟡 {m}")
            if result["new_count"] > 0:
                print(f"\n   New files ({result['new_count']}):")
                for n in result["details"]["new"]:
                    print(f"   🟢 {n}")
            return 1

    elif args.dry_run:
        # Dry run — just list files
        entries = hasher.hash_directory(root)
        print(f"Would hash {len(entries)} files:")
        for path in sorted(entries.keys()):
            print(f"  {path}")
        return 0

    else:
        # Generate mode
        print("[*] Scanning project files...")
        entries = hasher.hash_directory(root)

        # Also hash requirements
        req_path = root / "requirements-lock.txt"
        if req_path.exists():
            entries["requirements-lock.txt"] = hasher.hash_file(req_path)

        pc_req = root / "pc_agent" / "requirements.txt"
        if pc_req.exists():
            entries["pc_agent/requirements.txt"] = hasher.hash_file(pc_req)

        manifest.save(entries, metadata={
            "description": "AI Security Guardian — file integrity manifest",
            "usage": "Run 'python generate_integrity_manifest.py --verify' to check integrity",
        })

        print(f"✅ Generated integrity manifest: {len(entries)} files")
        print(f"   → {manifest.manifest_path}")
        print()
        print("💡 Tips:")
        print("   Run after git pull:  python generate_integrity_manifest.py")
        print("   Verify integrity:    python generate_integrity_manifest.py --verify")
        print("   Full self-audit:     python agent/self_audit.py --full")
        return 0


if __name__ == "__main__":
    sys.exit(main())
