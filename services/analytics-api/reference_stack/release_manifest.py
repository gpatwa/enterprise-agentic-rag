"""ADS-079: the final evidence manifest and the inputs to the human go/no-go review.

The generator links code, contracts, prompts, policies, context, corpus, thresholds, reports, and runbooks by digest, summarises every
evaluation, and lists everything that blocks a release. It NEVER decides and NEVER signs: `decision` is always `pending_human_review`,
every signature slot starts empty, and `verify_manifest` accepts a signature only when a named person has recorded a statement against
the manifest's own digest. Product, engineering, data-owner, security, and operations sign-off, and the final go/no-go, belong to people.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from app.operations.dashboard import GATES
from reference_stack.stack import SERVICE_ROOT

REPO_ROOT = SERVICE_ROOT.parent.parent
EXEC = REPO_ROOT / "docs" / "execution" / "enterprise-analytics"
REPORTS = EXEC / "reports"
PROGRAM = EXEC / "agentic-data-stack-program.yaml"
MANIFEST_VERSION = "ads-079-v1"
SIGN_OFF_ROLES = ("product", "engineering", "data_owner", "security", "operations")
M7_REPORTS = {
    "ADS-069": "ADS-069-operations-report.json",
    "ADS-071": "ADS-071-correctness-report.json",
    "ADS-072": "ADS-072-retrieval-report.json",
    "ADS-073": "ADS-073-abstention-report.json",
    "ADS-074": "ADS-074-isolation-report.json",
    "ADS-075": "ADS-075-reliability-report.json",
    "ADS-076": "ADS-076-performance-report.json",
    "ADS-077": "ADS-077-provider-report.json",
    "ADS-078": "ADS-078-onboarding-report.json",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path, patterns: tuple[str, ...], *, exclude=("tests", "__pycache__", "node_modules")) -> dict[str, str]:
    files: dict[str, str] = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and not any(part in exclude for part in path.parts):
                files[str(path.relative_to(REPO_ROOT))] = sha256_file(path)
    return files


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def report_summary(name: str, path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"name": name, "present": False, "ok": None, "approval": None}
    data = json.loads(path.read_text())
    if "ok" in data:
        ok = bool(data["ok"])
    elif "meets_thresholds" in data:
        ok = bool(data["meets_thresholds"])
    elif {"restore", "failover"} <= set(data):
        ok = all(d["result"]["passed"] for d in data.values())
    else:
        ok = None
    approval = (data.get("approval") or {}).get("status")
    unmet = [k for k, g in (data.get("gates") or {}).items() if isinstance(g, dict) and g.get("meets") is False]
    return {
        "name": name,
        "present": True,
        "file": _rel(path),
        "sha256": sha256_file(path),
        "ok": ok,
        "approval": approval,
        "unmet_gates": unmet,
    }


def threshold_files() -> list[dict[str, Any]]:
    patterns = (
        "reference_stack/**/*thresholds*.json",
        "reference_stack/**/*policy*.json",
        "resilience/*.json",
        "quotas/*.json",
        "delegation/*.json",
    )
    out = []
    for pattern in patterns:
        for path in sorted(SERVICE_ROOT.glob(pattern)):
            data = json.loads(path.read_text())
            approval = data.get("approval") or {}
            out.append(
                {
                    "file": str(path.relative_to(REPO_ROOT)),
                    "sha256": sha256_file(path),
                    "approval": approval.get("status"),
                    "approved_by": approval.get("approved_by"),
                }
            )
    return out


def program_state() -> dict[str, Any]:
    program = yaml.safe_load(PROGRAM.read_text())
    gates = {}
    for name, milestone in program["milestones"].items():
        if milestone.get("human_gate"):
            gates[name] = {
                "gate": milestone["human_gate"],
                "status": milestone.get("human_gate_status", "not_recorded"),
            }
    statuses: dict[str, int] = {}
    for task in program["tasks"].values():
        statuses[task["status"]] = statuses.get(task["status"], 0) + 1
    return {"human_gates": gates, "task_statuses": statuses}


def build_manifest(*, reports_dir: Path = REPORTS) -> dict[str, Any]:
    evaluations = [report_summary(g.packet + " " + g.gate_id, reports_dir / g.report) for g in GATES]
    evaluations += [report_summary(packet, reports_dir / file) for packet, file in M7_REPORTS.items()]
    corpus_approval = json.loads(
        (SERVICE_ROOT / "reference_stack" / "m7" / "corpus-approval.proposed.json").read_text()
    )
    thresholds = threshold_files()
    security = (
        json.loads((reports_dir / "ADS-067-security-report.json").read_text())
        if (reports_dir / "ADS-067-security-report.json").is_file()
        else {"findings": []}
    )
    open_findings = sorted(f["id"] for f in security["findings"] if f["status"] != "resolved")
    program = program_state()
    artifacts = {
        "code": _tree(SERVICE_ROOT, ("app/**/*.py", "reference_stack/**/*.py")),
        "contracts": _tree(REPO_ROOT / "packages" / "platform_contracts", ("*.py",)),
        "semantic_registry": _tree(SERVICE_ROOT, ("semantic_registry/**/*.json",)),
        "prompts": _tree(SERVICE_ROOT, ("app/prompt_registry/*.py",)),
        "policies_and_thresholds": {t["file"]: t["sha256"] for t in thresholds},
        "corpora": _tree(
            SERVICE_ROOT,
            ("reference_stack/m7/*corpus*.json", "reference_stack/golden/*.json", "reference_stack/*/*corpus*.json"),
        ),
        "reports": {e["file"]: e["sha256"] for e in evaluations if e.get("present")},
        "runbooks": _tree(EXEC, ("runbooks/*.md",)),
        "containers": _tree(REPO_ROOT, ("services/analytics-api/Dockerfile", "apps/analytics-web/Dockerfile")),
    }
    blocking: list[str] = []
    for e in evaluations:
        if not e["present"]:
            blocking.append(f"evaluation report missing: {e['name']}")
        elif e["ok"] is False:
            blocking.append(
                f"evaluation not met: {e['name']}"
                + (f" (unmet: {', '.join(e['unmet_gates'])})" if e["unmet_gates"] else "")
            )
    unapproved = [t["file"] for t in thresholds if t["approval"] != "approved"]
    if unapproved:
        blocking.append(f"{len(unapproved)} threshold/policy files are not approved by a person")
    if corpus_approval["approval"]["status"] != "approved":
        blocking.append("the reference corpus is not approved by its definition owner and results owner")
    for name, gate in program["human_gates"].items():
        if gate["status"] != "approved":
            blocking.append(f"human gate not approved: {name} ({gate['gate']})")
    if program["task_statuses"].get("review"):
        blocking.append(
            f"{program['task_statuses']['review']} packets are `review` with no independent review recorded"
        )
    if open_findings:
        blocking.append("security findings not resolved: " + ", ".join(open_findings))
    blocking.append("no signed human sign-off yet from: " + ", ".join(SIGN_OFF_ROLES))
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "base_commit": _git("rev-parse", "HEAD"),
        "base_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "artifacts": artifacts,
        "models": {
            "selected": None,
            "note": "no real model or provider has been selected or evaluated; evaluations used a scripted model",
        },
        "containers_note": "no images were built or pushed; only Dockerfile digests are listed",
        "evaluations": evaluations,
        "program": program,
        "open_security_findings": open_findings,
        "corpus_approval": corpus_approval["approval"],
        "decision": "pending_human_review",
        "blocking_reasons": blocking,
        "signatures": {role: None for role in SIGN_OFF_ROLES},
    }
    manifest["manifest_digest"] = manifest_digest(manifest)
    return manifest


def manifest_digest(manifest: dict[str, Any]) -> str:
    body = {k: v for k, v in manifest.items() if k not in {"manifest_digest", "signatures", "decision", "ok", "packet"}}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def verify_manifest(manifest: dict[str, Any]) -> list[str]:
    """Problems found: a changed artifact, a wrong digest, an auto-decision, or a signature a person did not make."""
    problems: list[str] = []
    if manifest.get("manifest_digest") != manifest_digest(manifest):
        problems.append("manifest digest does not match its content")
    if manifest.get("decision") != "pending_human_review":
        problems.append(
            "the generator's decision must remain pending_human_review; a go/no-go is recorded by people in the review record"
        )
    for group, files in manifest["artifacts"].items():
        for rel, digest in files.items():
            path = REPO_ROOT / rel
            if not path.is_file():
                problems.append(f"{group}: {rel} is missing")
            elif sha256_file(path) != digest:
                problems.append(f"{group}: {rel} changed since the manifest was generated")
    for role, signature in manifest["signatures"].items():
        if signature is None:
            continue
        if not (
            isinstance(signature, dict)
            and signature.get("signer")
            and signature.get("statement")
            and signature.get("manifest_digest") == manifest["manifest_digest"]
        ):
            problems.append(f"signature for {role} is not a named person's statement over this manifest digest")
    return problems


def sign_off_complete(manifest: dict[str, Any]) -> bool:
    return not verify_manifest(manifest) and all(manifest["signatures"].get(role) for role in SIGN_OFF_ROLES)


def render_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# ADS-079: Final Evidence Manifest (input to the human go/no-go review)",
        "",
        f"Manifest `{manifest['manifest_version']}`, digest `{manifest['manifest_digest'][:16]}`, generated at `{manifest['base_commit'][:12]}` on `{manifest['base_branch']}`.",
        "",
        f"**Decision: `{manifest['decision']}`.** This document does not decide and is not signed. Product, engineering, data owner, security, and operations must each sign against the digest, and a person records the go/no-go.",
        "",
        "## Blocking reasons",
        "",
    ] + [f"- {r}" for r in manifest["blocking_reasons"]]
    lines += [
        "",
        "## Evaluations",
        "",
        "| Evaluation | Present | Met | Thresholds approval | Unmet gates |",
        "|---|:---:|:---:|---|---|",
    ]
    for e in manifest["evaluations"]:
        met = "n/a" if e["ok"] is None else ("yes" if e["ok"] else "**NO**")
        lines.append(
            f"| {e['name']} | {'yes' if e['present'] else '**NO**'} | {met} | {e.get('approval')} | {', '.join(e.get('unmet_gates') or []) or '-'} |"
        )
    lines += ["", "## Linked artifacts", ""] + [
        f"- **{group}**: {len(files)} files" for group, files in manifest["artifacts"].items()
    ]
    lines += [
        "",
        f"Models: {manifest['models']['note']}. Containers: {manifest['containers_note']}.",
        "",
        "## Human gates",
        "",
    ]
    lines += [f"- {name}: {g['gate']} = **{g['status']}**" for name, g in manifest["program"]["human_gates"].items()]
    lines += (
        ["", f"Task statuses: {manifest['program']['task_statuses']}.", "", "## Signatures", ""]
        + [f"- {role}: {'**signed**' if sig else 'not signed'}" for role, sig in manifest["signatures"].items()]
        + [""]
    )
    return "\n".join(lines)


def run_manifest() -> dict[str, Any]:
    """`ok` means only that the manifest is internally consistent and honest (no auto-decision); it is NOT a go."""
    manifest = build_manifest()
    manifest["packet"] = "ADS-079"
    manifest["ok"] = not verify_manifest(manifest)
    return manifest
