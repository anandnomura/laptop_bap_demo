# How a BAP deny prevents execution

## Claude Code path

1. Claude proposes a tool call; it has not executed yet.
2. Claude Code invokes the managed `PreToolUse` hook and sends JSON on standard input.
3. Signed `claude_guard.exe` normalizes the event and calls the signed laptop connector through the Windows named pipe.
4. The connector binds the request to the registered user, device, agent run, captured task, normalized action, and resource.
5. The connector sends the request over mTLS to central BAP.
6. BAP evaluates Cedar and returns `ALLOW`, `REQUIRE_APPROVAL`, or `DENY`, including policy evidence.
7. For `DENY`, ClaudeGuard prints a Claude hook result like:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Cedar denied under forbid-destructive-database-actions"
  }
}
```

8. Claude Code cancels the tool call and gives the reason back to the model/user. `bap_resource_client.exe` is not started.

For `ALLOW`, ClaudeGuard adds only `--bap-session <id>` to the protected command. The grant stays inside the connector. For `REQUIRE_APPROVAL`, Claude asks, but the write grant is not issued until the approval is verified and Cedar permits the original action on re-evaluation.

## Hooks are not the final boundary

Agent hooks improve control and user experience, but a product defect, timeout behavior, altered agent, or manual shell command must not create resource access. The resource gateway is the final authorization boundary:

- the laptop cannot route directly to the protected resource in production;
- only the connector can reach the gateway, using its device-bound mTLS identity;
- the gateway independently verifies grant signature, expiry, revocation, audience, agent run, action, and resource;
- the resource accepts traffic only from its gateway network/service identity.

Therefore, even if an agent ignores or bypasses a hook, it still lacks both a usable route and a valid BAP grant.

## Negative-case matrix

| Attempt | First denial | Final protection |
|---|---|---|
| Cedar returns explicit deny | ClaudeGuard returns `permissionDecision=deny` | No grant exists; gateway would deny |
| Unknown command/action | Connector/BAP default deny | No matching Cedar permit |
| Missing session | Connector denies | No connector-held grant |
| Fabricated token | Resource gateway rejects signature | Request never reaches resource |
| Reuse grant for another action/resource/run | Gateway rejects binding mismatch | Request never reaches resource |
| Expired or revoked grant | Gateway rejects state/time | Request never reaches resource |
| Direct resource request | Network policy/resource service denies | Gateway-only service identity required |
| Connector/BAP/Cedar unavailable | Adapter/connector fails closed | Gateway cannot receive a valid new grant |

The dashboard is evidence, not enforcement. Removing or hiding the dashboard changes nothing about these decisions.
