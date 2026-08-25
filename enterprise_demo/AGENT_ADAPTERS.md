# Adapting BAP to Claude Code, Cursor, Copilot, and other agents

## Agent-neutral contract

BAP should not contain vendor-specific hook payloads. Each agent gets a small signed adapter with five responsibilities:

1. Register and close an agent run.
2. Capture delegated task intent.
3. Normalize a proposed tool call into `action`, `resource`, and non-secret parameters.
4. Translate BAP `ALLOW`, `REQUIRE_APPROVAL`, and `DENY` into the vendor's native decision format.
5. Report completion/failure evidence with the same correlation IDs.

Every Windows adapter calls the same laptop connector named pipe. The connector and central BAP APIs remain unchanged. An adapter never embeds policy, holds mTLS credentials, or receives the signed grant.

## Integration comparison

| Agent surface | Interception mechanism | Adapter work | Enterprise hardening |
|---|---|---|---|
| Claude Code | `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `SessionEnd` | Current `claude_guard.exe` already maps these events | Deploy through managed settings; signed Program Files binary; managed-hooks-only policy |
| Cursor IDE/agent | `sessionStart`, `preToolUse`, `beforeShellExecution`, `beforeMCPExecution`, post-use and session hooks | Create `cursor_guard.exe` or a vendor-normalization mode that accepts Cursor JSON and returns Cursor permission JSON | Use enterprise hooks at `C:\ProgramData\Cursor\hooks.json`, `failClosed: true`, signed binary, and endpoint policy preventing weaker user/project hooks from overriding controls |
| GitHub Copilot CLI | `preToolUse`, session/prompt/post hooks | Create `copilot_guard.exe`, or use Copilot's Claude-compatible `PreToolUse` payload and translate remaining lifecycle events | Centrally manage the CLI/hook configuration; account for documented timeout semantics; retain gateway enforcement |
| Copilot SDK application | Programmatic `onPreToolUse` and lifecycle callbacks | Call a BAP adapter library from the host application and map the decision object | Sign/control the host application and do not expose an approve-all permission handler around BAP |
| MCP-capable agent | A managed BAP-aware MCP proxy/server | Expose only cataloged BAP tools; proxy each call through the connector/gateway | Allow only managed MCP servers and block direct resource/network routes |
| Agent without reliable pre-tool hooks | BAP-aware tools/MCP plus gateway enforcement | No hook-based early denial; resource calls still require BAP | Treat hooks as unavailable; rely on controlled tools, sandboxing, egress policy, and gateway-only resources |

Cursor currently documents enterprise-managed Windows hooks under `C:\ProgramData\Cursor\hooks.json`, supports `preToolUse` and resource-specific hooks, and provides `failClosed: true` for security-critical hooks. GitHub Copilot CLI documents `preToolUse`, including allow/deny/ask results and Claude-compatible `PreToolUse` payloads. These vendor features can change, so certify each supported client/version before rollout.

References: [Cursor hooks](https://cursor.com/docs/hooks), [GitHub Copilot hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference), and [Copilot SDK pre-tool hook](https://docs.github.com/en/copilot/how-tos/copilot-sdk/hooks/pre-tool-use).

## Adapter certification checklist

- All execution-capable tools are intercepted: shell, PowerShell, MCP, file, browser/network, subagents, and vendor extensions.
- A deny is proven to stop execution, not merely display a message.
- Hook crash, invalid JSON, and timeout behavior are tested for the exact supported version.
- Session IDs cannot be supplied or reused by another untrusted process.
- The named-pipe server verifies client process identity and signature; production uses full WinVerifyTrust and explicit pipe ACLs.
- Only signed resource adapters can request execution.
- Direct network access remains blocked even when the agent is launched without hooks.
- Upgrade rings rerun positive, negative, bypass, timeout, and downgrade tests before a new agent version is allowed.

## Recommended implementation order

1. Keep the connector/BAP/grant/gateway contract vendor-neutral.
2. Extract Claude event normalization from policy/resource classification.
3. Build a shared adapter test suite with canonical events and expected BAP envelopes.
4. Implement and sign one thin adapter per vendor payload/response contract.
5. Add managed configuration examples and version certification for each client.
6. Onboard MCP and resource gateways once, then reuse them across every agent.
