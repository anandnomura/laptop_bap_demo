from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ACTION_IDS = {
    "database.read": "databaseRead",
    "database.write": "databaseWrite",
    "database.delete": "databaseDelete",
}


@dataclass(frozen=True)
class PolicyDecision:
    effect: str
    reason: str
    rule_id: str
    bundle_id: str
    revision: str
    bundle_sha256: str
    grant_ttl_seconds: int


class PolicyBundle:
    """Invokes the official Cedar CLI for the production-shaped laptop demo."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.policies = directory / "policies.cedar"
        self.schema = directory / "bap.cedarschema"
        self.resources = directory / "resources.cedarentities.json"
        self.metadata = json.loads((directory / "policy-bundle.json").read_text(encoding="utf-8"))
        default_cli = directory.parent / "runtime" / "tools" / f"cedar-{self.metadata['cedar_cli_version']}" / "cedar.exe"
        self.cedar = Path(os.environ.get("BAP_CEDAR_CLI", default_cli))
        if not self.cedar.exists():
            raise OSError(
                f"Official Cedar CLI is missing at {self.cedar}; run orchestration/install_cedar_cli.ps1"
            )
        self.rule_ids = re.findall(r'@id\("([^"]+)"\)', self.policies.read_text(encoding="utf-8"))
        self.bundle_sha256 = self._bundle_digest()
        self._validate()

    def evaluate(self, request: dict[str, Any], *, human_approved: bool = False) -> PolicyDecision:
        action = str(request.get("action", ""))
        if action not in ACTION_IDS:
            return self._decision("DENY", "default-deny", "The requested action is not in the BAP Cedar schema")

        direct = self._authorize(request, ACTION_IDS[action], human_approved)
        if direct[0] == "ALLOW":
            return self._decision("ALLOW", direct[1], "Cedar permitted the requested action")

        if action == "database.write" and not human_approved:
            approval = self._authorize(request, "requestDatabaseWriteApproval", False)
            if approval[0] == "ALLOW":
                return self._decision(
                    "REQUIRE_APPROVAL",
                    approval[1],
                    "Cedar permits requesting approval, but does not yet permit the write",
                )

        rule_id = direct[1] if direct[1] != "no-applicable-policy" else "default-deny"
        return self._decision("DENY", rule_id, "Cedar denied the requested action")

    def _authorize(self, request: dict[str, Any], cedar_action: str, human_approved: bool) -> tuple[str, str]:
        cedar_request = {
            "principal": self._entity_literal("BAP::User", str(request.get("user", "unknown"))),
            "action": self._entity_literal("BAP::Action", cedar_action),
            "resource": self._entity_literal("BAP::DataStore", str(request.get("resource", ""))),
            "context": {
                "agent": str(request.get("agent", "unknown")),
                "agentClass": "laptop-agent",
                "registered": bool(request.get("agent_run")),
                "deviceManaged": bool(request.get("device")),
                "humanApproved": human_approved,
                "agentRun": str(request.get("agent_run", "")),
                "task": str(request.get("task", ""))[:300],
            },
        }
        with tempfile.TemporaryDirectory(prefix="bap-cedar-") as temporary:
            request_path = Path(temporary) / "request.cedarauth.json"
            request_path.write_text(json.dumps(cedar_request), encoding="utf-8")
            completed = subprocess.run(
                [
                    self.cedar,
                    "authorize",
                    "--policies", self.policies,
                    "--schema", self.schema,
                    "--schema-format", "cedar",
                    "--entities", self.resources,
                    "--request-json", request_path,
                    "--verbose",
                    "--error-format", "plain",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )
        combined_output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        if not re.search(r"^(ALLOW|DENY)$", combined_output, re.MULTILINE):
            raise ValueError(f"Cedar evaluation failed: {(completed.stderr or completed.stdout).strip()}")
        effect = "ALLOW" if re.search(r"^ALLOW$", combined_output, re.MULTILINE) else "DENY"
        matched = [rule_id for rule_id in self.rule_ids if rule_id in combined_output]
        return effect, matched[0] if matched else "no-applicable-policy"

    def _validate(self) -> None:
        completed = subprocess.run(
            [
                self.cedar,
                "validate",
                "--policies", self.policies,
                "--schema", self.schema,
                "--schema-format", "cedar",
                "--deny-warnings",
                "--error-format", "plain",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if completed.returncode != 0:
            raise ValueError(f"Cedar policy validation failed: {(completed.stderr or completed.stdout).strip()}")

    @staticmethod
    def _entity_literal(entity_type: str, entity_id: str) -> str:
        escaped = entity_id.replace("\\", "\\\\").replace('"', '\\"')
        return f'{entity_type}::"{escaped}"'

    def _decision(self, effect: str, rule_id: str, reason: str) -> PolicyDecision:
        return PolicyDecision(
            effect=effect,
            reason=reason,
            rule_id=rule_id,
            bundle_id=self.metadata["bundle_id"],
            revision=self.metadata["revision"],
            bundle_sha256=self.bundle_sha256,
            grant_ttl_seconds=int(self.metadata["grant_ttl_seconds"]),
        )

    def _bundle_digest(self) -> str:
        digest = hashlib.sha256()
        for path in (self.policies, self.schema, self.resources, self.directory / "policy-bundle.json"):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()
