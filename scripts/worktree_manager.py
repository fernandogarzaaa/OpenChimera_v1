import os
import subprocess
import shutil
import uuid
import logging
import argparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WorktreeManager:
    """
    Manages Git worktrees to allow OpenClaw agents to run in isolated, temporary
    parallel directories to prevent file collisions.
    """
    def __init__(self, repo_path: str):
        self.repo_path = os.path.abspath(repo_path)
        if not os.path.exists(os.path.join(self.repo_path, '.git')):
            raise ValueError(f"Not a git repository: {self.repo_path}")

    def _run_cmd(self, cmd: list, cwd: str = None) -> str:
        if cwd is None:
            cwd = self.repo_path
        
        try:
            result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}\nError: {e.stderr}")
            raise RuntimeError(f"Git command failed: {e.stderr}")

    def create_worktree(self, branch_name: str, worktree_dir: str = None) -> str:
        """Creates a new git worktree with the given branch name."""
        if worktree_dir is None:
            worktree_dir = os.path.join(self.repo_path, '.worktrees', branch_name)
            
        worktree_dir = os.path.abspath(worktree_dir)
        
        os.makedirs(os.path.dirname(worktree_dir), exist_ok=True)
        
        logger.info(f"Creating worktree at {worktree_dir} for branch {branch_name}")
        
        try:
            self._run_cmd(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"])
            branch_exists = True
        except RuntimeError:
            branch_exists = False
            
        if not branch_exists:
            # Create worktree and new branch
            self._run_cmd(["git", "worktree", "add", "-b", branch_name, worktree_dir])
        else:
            # Create worktree with existing branch
            self._run_cmd(["git", "worktree", "add", worktree_dir, branch_name])
            
        return worktree_dir

    def remove_worktree(self, worktree_dir: str, force: bool = False):
        """Removes a git worktree."""
        worktree_dir = os.path.abspath(worktree_dir)
        logger.info(f"Removing worktree at {worktree_dir}")
        
        cmd = ["git", "worktree", "remove"]
        if force:
            cmd.append("-f")
        cmd.append(worktree_dir)
        
        self._run_cmd(cmd)

    def merge_and_cleanup(self, branch_name: str, worktree_dir: str, target_branch: str = "main"):
        """Merges the worktree branch into target_branch and cleans up the worktree."""
        logger.info(f"Merging branch {branch_name} into {target_branch}")
        
        # Remove the worktree first
        self.remove_worktree(worktree_dir, force=True)
        
        # Checkout target branch
        self._run_cmd(["git", "checkout", target_branch])
        
        # Merge
        try:
            self._run_cmd(["git", "merge", branch_name])
            logger.info(f"Successfully merged {branch_name} into {target_branch}")
        except RuntimeError as e:
            logger.error(f"Merge conflict or error merging {branch_name} into {target_branch}. Aborting merge.")
            try:
                self._run_cmd(["git", "merge", "--abort"])
            except RuntimeError:
                pass
            raise e
            
        # Delete the branch
        self._run_cmd(["git", "branch", "-d", branch_name])
        logger.info(f"Deleted branch {branch_name}")

def main():
    parser = argparse.ArgumentParser(description="Manage Git Worktrees for OpenClaw Agent Sandboxing")
    parser.add_argument("--repo", default=".", help="Path to git repository")
    subparsers = parser.add_subparsers(dest="action", help="Action to perform", required=True)

    add_parser = subparsers.add_parser("add", help="Create a new worktree")
    add_parser.add_argument("branch", help="Branch name")
    add_parser.add_argument("--path", help="Path to worktree directory (optional)")

    remove_parser = subparsers.add_parser("remove", help="Remove a worktree")
    remove_parser.add_argument("path", help="Path to worktree directory")
    remove_parser.add_argument("--force", action="store_true", help="Force remove")

    merge_parser = subparsers.add_parser("merge", help="Merge branch and cleanup worktree")
    merge_parser.add_argument("branch", help="Branch name")
    merge_parser.add_argument("path", help="Path to worktree directory")
    merge_parser.add_argument("--target", default="main", help="Target branch to merge into")

    args = parser.parse_args()

    try:
        manager = WorktreeManager(args.repo)
        if args.action == "add":
            wt_path = manager.create_worktree(args.branch, args.path)
            print(f"Worktree created at: {wt_path}")
        elif args.action == "remove":
            manager.remove_worktree(args.path, args.force)
            print(f"Worktree removed: {args.path}")
        elif args.action == "merge":
            manager.merge_and_cleanup(args.branch, args.path, args.target)
            print(f"Merged {args.branch} into {args.target} and cleaned up.")
    except Exception as e:
        logger.error(f"Operation failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()
