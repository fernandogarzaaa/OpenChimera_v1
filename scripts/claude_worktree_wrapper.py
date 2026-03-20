import subprocess
import sys
import os
import worktree_manager
import debate_protocol

# Integration of WorktreeManager and Debate Protocol Auditor
# This script serves as a wrapper to execute git/claude commands within isolated worktrees.

def run_auditor():
    """Triggers debate_protocol.py as a pre-commit audit."""
    print("Running Debate Protocol Audit...")
    if not debate_protocol.audit():
        print("Audit FAILED. Commit aborted.")
        sys.exit(1)
    print("Audit PASSED.")

def main():
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        # If the command is 'commit', trigger the audit
        if command == "commit":
            run_auditor()
            subprocess.run(["git", "commit"] + sys.argv[2:])
        else:
            # Handle worktree creation if invoked with a specific flag or action
            if command == "worktree-add":
                branch = sys.argv[2]
                manager = worktree_manager.WorktreeManager(os.getcwd())
                wt_path = manager.create_worktree(branch)
                print(f"Worktree created at: {wt_path}")
            else:
                # Fallback to direct git command
                subprocess.run(["git"] + sys.argv[1:])
    else:
        print("Usage: claude_worktree_wrapper.py [commit|worktree-add|git-cmd]")

if __name__ == "__main__":
    main()
