from dabba.cli.permissions import PermissionManager

REPO = str(__import__("pathlib").Path(__file__).resolve().parents[2])


def test_commit_on_protected_branch_is_hard_blocked():
    pm = PermissionManager(mode="allow", persistent=False)
    pm._current_git_branch = staticmethod(lambda cwd: "main")
    assert pm.check_tool("shell_exec", {"command": "git commit -m 'x'", "cwd": REPO}) is False
    assert "protected branch" in pm.get_last_denial_reason()


def test_commit_on_feature_branch_is_unaffected():
    pm = PermissionManager(mode="allow", persistent=False)
    pm._current_git_branch = staticmethod(lambda cwd: "feature/x")
    assert pm.check_tool("shell_exec", {"command": "git commit -m 'x'", "cwd": REPO}) is True


def test_force_push_on_protected_branch_cannot_be_overridden():
    pm = PermissionManager(mode="allow", persistent=False, confirm_fn=lambda name, args: True)
    pm._current_git_branch = staticmethod(lambda cwd: "main")
    assert pm.check_tool("shell_exec", {"command": "git push --force origin main", "cwd": REPO}) is False


def test_force_push_on_feature_branch_requires_confirmation():
    pm_denied = PermissionManager(mode="allow", persistent=False)
    pm_denied._current_git_branch = staticmethod(lambda cwd: "feature/x")
    assert pm_denied.check_tool("shell_exec", {"command": "git push -f origin feature/x", "cwd": REPO}) is False

    pm_approved = PermissionManager(mode="allow", persistent=False, confirm_fn=lambda name, args: True)
    pm_approved._current_git_branch = staticmethod(lambda cwd: "feature/x")
    assert pm_approved.check_tool("shell_exec", {"command": "git push -f origin feature/x", "cwd": REPO}) is True


def test_plain_push_on_protected_branch_needs_confirmation_but_is_not_hard_blocked():
    pm_approved = PermissionManager(mode="allow", persistent=False, confirm_fn=lambda name, args: True)
    pm_approved._current_git_branch = staticmethod(lambda cwd: "main")
    assert pm_approved.check_tool("shell_exec", {"command": "git push origin main", "cwd": REPO}) is True


def test_readonly_git_commands_are_unaffected():
    pm = PermissionManager(mode="allow", persistent=False)
    pm._current_git_branch = staticmethod(lambda cwd: "main")
    assert pm.check_tool("shell_exec", {"command": "git status", "cwd": REPO}) is True
    assert pm.check_tool("shell_exec", {"command": "git log --oneline -5", "cwd": REPO}) is True


def test_non_git_commands_are_unaffected():
    pm = PermissionManager(mode="allow", persistent=False)
    assert pm.check_tool("shell_exec", {"command": "ls -la", "cwd": REPO}) is True
