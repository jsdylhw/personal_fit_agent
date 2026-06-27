"""permission 模块单测 — 三道闸门."""

from __future__ import annotations

import pytest

from agent.workflow.permission import (
    DENY_LIST,
    PERMISSION_RULES,
    PermissionDecision,
    PermissionResult,
    check_deny_list,
    check_permission,
    check_rules,
)


class TestDenyList:
    def test_empty_deny_always_passes(self):
        assert check_deny_list("any_tool", {}) is None

    def test_deny_applies_to_matching_tool(self):
        # 临时加一条
        DENY_LIST.append(("test_deny_tool", "Test denial"))
        try:
            assert check_deny_list("test_deny_tool", {}) == "Test denial"
        finally:
            DENY_LIST.pop()

    def test_deny_ignores_non_matching_tool(self):
        assert check_deny_list("safe_tool", {}) is None


class TestCheckRules:
    def test_upload_always_requires_confirmation(self):
        reason = check_rules("upload_strava_activity", {})
        assert reason is not None
        assert "Strava" in reason

    def test_sync_always_requires_confirmation(self):
        reason = check_rules("sync_garmin_activities", {})
        assert reason is not None
        assert "Garmin" in reason

    def test_upload_force_still_requires_confirmation(self):
        # force 不自动放行
        reason = check_rules("upload_strava_activity", {"force": True})
        assert reason is not None

    def test_write_tools_force_still_requires_confirmation(self):
        reason = check_rules("generate_summary_file", {"force": True})
        assert reason is not None

    def test_readonly_tool_no_confirmation(self):
        reason = check_rules("analyze_single_activity", {})
        assert reason is None

    def test_resolve_tool_no_confirmation(self):
        reason = check_rules("resolve_recent_activities", {})
        assert reason is None


class TestCheckPermission:
    def test_hard_deny(self):
        DENY_LIST.append(("blocked_tool", "已禁用"))
        try:
            result = check_permission("blocked_tool", {})
            assert result.allowed is False
            assert result.decision == PermissionDecision.DENY
            assert result.denied is True
            assert result.needs_confirmation is False
            assert "已禁用" in result.block_message
        finally:
            DENY_LIST.pop()

    def test_needs_confirmation_first_time(self):
        result = check_permission("upload_strava_activity", {}, has_confirmed=False)
        assert result.allowed is False
        assert result.decision == PermissionDecision.ASK
        assert result.needs_confirmation is True
        assert "Strava" in result.reason

    def test_allowed_when_confirmed(self):
        result = check_permission("upload_strava_activity", {}, has_confirmed=True)
        assert result.allowed is True
        assert result.decision == PermissionDecision.ALLOW

    def test_safe_tool_allowed(self):
        result = check_permission("analyze_single_activity", {})
        assert result.allowed is True

    def test_safe_tool_no_reason(self):
        result = check_permission("resolve_recent_activities", {"limit": 5})
        assert result.allowed is True
        assert result.reason == ""
