from pathlib import Path
from typing import Optional, List

from exegol.utils.ConstantConfig import ConstantConfig
from exegol.utils.ExeLog import logger, console


# SDK Documentation : https://gitpython.readthedocs.io/en/stable/index.html

class GitUtils:
    """Utility class between exegol and the Git SDK"""

    def __init__(self, path: Optional[Path] = None, name: str = "wrapper", subject: str = "source code"):
        """Init git local repository object / SDK"""
        if path is None:
            path = ConstantConfig.src_root_path_obj
        self.isAvailable = False
        self.__is_submodule = False
        self.__repo_path = path
        self.__git_name: str = name
        self.__git_subject: str = subject
        abort_loading = False
        # Check if .git directory exist
        try:
            test_git_dir = self.__repo_path / '.git'
            if test_git_dir.is_file():
                logger.debug("Git submodule repository detected")
                self.__is_submodule = True
            elif not test_git_dir.is_dir():
                raise ReferenceError
        except ReferenceError:
            if self.__git_name == "wrapper":
                logger.warning("Exegol has not been installed via git clone. Skipping wrapper auto-update operation.")
                if self.__repo_path.name == "site-packages":
                    logger.info("If you have installed Exegol with pip, check for an update with the command "
                                "[green]pip3 install exegol --upgrade[/green]")
            # TODO check pip with submodules
            abort_loading = True
        # locally import git in case git is not installed of the system
        try:
            from git import Repo, Remote, InvalidGitRepositoryError, FetchInfo
        except ModuleNotFoundError:
            logger.debug("Git module is not installed.")
            return
        except ImportError:
            logger.error("Unable to find git tool locally. Skipping git operations.")
            return
        self.__gitRepo: Optional[Repo] = None
        self.__gitRemote: Optional[Remote] = None
        self.__fetchBranchInfo: Optional[FetchInfo] = None

        if abort_loading:
            return
        logger.debug(f"Loading git at {self.__repo_path}")
        try:
            self.__gitRepo = Repo(str(self.__repo_path))
            self.__init_repo()
        except InvalidGitRepositoryError as err:
            logger.verbose(err)
            logger.warning("Error while loading local git repository. Skipping all git operation.")

    def __init_repo(self):
        self.isAvailable = True
        logger.debug("Git repository successfully loaded")
        if len(self.__gitRepo.remotes) > 0:
            self.__gitRemote = self.__gitRepo.remotes['origin']
        else:
            logger.warning("No remote git origin found on repository")
            logger.debug(self.__gitRepo.remotes)
        self.__initSubmodules()

    def clone(self, repo_url: str, optimize_disk_space: bool = True) -> bool:
        if self.isAvailable:
            logger.warning(f"The {self.getName()} repo is already cloned.")
            return False
        # locally import git in case git is not installed of the system
        try:
            from git import Repo, Remote, InvalidGitRepositoryError, FetchInfo
        except ModuleNotFoundError:
            logger.debug("Git module is not installed.")
            return False
        except ImportError:
            logger.error(f"Unable to find git on your machine. The {self.getName()} repository cannot be cloned.")
            logger.warning("Please install git to support this feature.")
            return False
        custom_options = []
        if optimize_disk_space:
            custom_options.append('--depth=1')
        # TODO add console loader / progress bar via TUI
        self.__gitRepo = Repo.clone_from(repo_url, str(self.__repo_path), multi_options=custom_options)
        self.__init_repo()
        return True

    def getCurrentBranch(self) -> Optional[str]:
        """Get current git branch name"""
        assert self.isAvailable
        assert self.__gitRepo is not None
        try:
            return str(self.__gitRepo.active_branch)
        except TypeError:
            logger.debug("Git HEAD is detached, cant find the current branch.")
            return None

    def listBranch(self) -> List[str]:
        """Return a list of str of all remote git branch available"""
        assert self.isAvailable
        result: List[str] = []
        if self.__gitRemote is None:
            return result
        for branch in self.__gitRemote.fetch():
            branch_parts = branch.name.split('/')
            if len(branch_parts) < 2:
                logger.warning(f"Branch name is not correct: {branch.name}")
                result.append(branch.name)
            else:
                result.append(branch_parts[1])
        return result

    def safeCheck(self) -> bool:
        """Check the status of the local git repository,
        if there is pending change it is not safe to apply some operations"""
        assert self.isAvailable
        if self.__gitRepo is None or self.__gitRemote is None:
            return False
        # Submodule changes must be ignored to update the submodules sources independently of the wrapper
        is_dirty = self.__gitRepo.is_dirty(submodules=False)
        if is_dirty:
            logger.warning("Local git have unsaved change. Skipping source update.")
        return not is_dirty

    def isUpToDate(self, branch: Optional[str] = None) -> bool:
        """Check if the local git repository is up-to-date.
        This method compare the last commit local and the ancestor."""
        assert self.isAvailable
        if branch is None:
            branch = self.getCurrentBranch()
            if branch is None:
                logger.warning("No branch is currently attached to the git repository. The up-to-date status cannot be checked.")
                return False
        assert self.__gitRepo is not None
        assert self.__gitRemote is not None
        # Get last local commit
        current_commit = self.__gitRepo.heads[branch].commit
        # Get last remote commit
        fetch_result = self.__gitRemote.fetch()
        try:
            self.__fetchBranchInfo = fetch_result[f'{self.__gitRemote}/{branch}']
        except IndexError:
            logger.warning("The selected branch is local and cannot be updated.")
            return True

        logger.debug(f"Fetch flags : {self.__fetchBranchInfo.flags}")
        logger.debug(f"Fetch note : {self.__fetchBranchInfo.note}")
        logger.debug(f"Fetch old commit : {self.__fetchBranchInfo.old_commit}")
        logger.debug(f"Fetch remote path : {self.__fetchBranchInfo.remote_ref_path}")
        from git import FetchInfo
        # Bit check to detect flags info
        if self.__fetchBranchInfo.flags & FetchInfo.HEAD_UPTODATE != 0:
            logger.debug("HEAD UP TO DATE flag detected")
        if self.__fetchBranchInfo.flags & FetchInfo.FAST_FORWARD != 0:
            logger.debug("FAST FORWARD flag detected")
        if self.__fetchBranchInfo.flags & FetchInfo.ERROR != 0:
            logger.debug("ERROR flag detected")
        if self.__fetchBranchInfo.flags & FetchInfo.FORCED_UPDATE != 0:
            logger.debug("FORCED_UPDATE flag detected")
        if self.__fetchBranchInfo.flags & FetchInfo.REJECTED != 0:
            logger.debug("REJECTED flag detected")
        if self.__fetchBranchInfo.flags & FetchInfo.NEW_TAG != 0:
            logger.debug("NEW TAG flag detected")

        remote_commit = self.__fetchBranchInfo.commit
        # Check if remote_commit is an ancestor of the last local commit (check if there is local commit ahead)
        return self.__gitRepo.is_ancestor(remote_commit, current_commit)

    def update(self) -> bool:
        """Update local git repository within current branch"""
        assert self.isAvailable
        if not self.safeCheck():
            return False
        # Check if the git branch status is not detached
        if self.getCurrentBranch() is None:
            return False
        if self.isUpToDate():
            logger.info(f"Git branch '{self.getCurrentBranch()}' is already up-to-date.")
            return False
        if self.__gitRemote is not None:
            logger.info(f"Using branch '{self.getCurrentBranch()}' on {self.getName()} repository")
            self.__gitRemote.pull()
            logger.success("Git successfully updated")
            return True
        return False

    def __initSubmodules(self):
        """Init (and update) git sub repositories (not source code)"""
        if self.isSubModule():
            # Disable submodule init from submodule repo
            return
        logger.verbose(f"Git {self.getName()} init submodules")
        blacklist_heavy_modules = ["exegol-resources"]
        with console.status(f"Initialization of git submodules", spinner_style="blue"):
            for subm in self.__gitRepo.iter_submodules():
                if subm.name in blacklist_heavy_modules:
                    continue
                logger.debug(f"Init submodule '{subm.name}'")
                subm.update(recursive=True)

    def submoduleSourceUpdate(self, name: str) -> bool:
        """Update source code from the 'name' git submodule"""
        if not self.isAvailable:
            return False
        assert self.__gitRepo is not None
        try:
            submodule = self.__gitRepo.submodule(name)
        except ValueError:
            logger.debug(f"Git submodule '{name}' not found.")
            return False
        from git.exc import RepositoryDirtyError
        try:
            # TODO add TUI progress
            with console.status(f"Updating submodule {name}", spinner_style="blue"):
                submodule.update(to_latest_revision=True, recursive=True)
            logger.success(f"Submodule {name} successfully updated.")
            return True
        except RepositoryDirtyError:
            logger.warning(f"Submodule {name} cannot be updated automatically as long as there are local modifications.")
            logger.error("Aborting git submodule update.")
        logger.empty_line()
        return False

    def checkout(self, branch: str) -> bool:
        """Change local git branch"""
        assert self.isAvailable
        if not self.safeCheck():
            return False
        if branch == self.getCurrentBranch():
            logger.warning(f"Branch '{branch}' is already the current branch")
            return False
        assert self.__gitRepo is not None
        from git.exc import GitCommandError
        try:
            # If git local branch didn't exist, change HEAD to the origin branch and create a new local branch
            if branch not in self.__gitRepo.heads:
                self.__gitRepo.references['origin/' + branch].checkout()
                self.__gitRepo.create_head(branch)
            self.__gitRepo.heads[branch].checkout()
        except GitCommandError as e:
            logger.error("Unable to checkout to the selected branch. Skipping operation.")
            logger.debug(e)
            return False
        except IndexError as e:
            logger.error("Unable to find the selected branch. Skipping operation.")
            logger.debug(e)
            return False
        logger.success(f"Git successfully checkout to '{branch}'")
        return True

    def getName(self) -> str:
        """Git name getter"""
        return self.__git_name

    def getSubject(self) -> str:
        """Git subject getter"""
        return self.__git_subject

    def isSubModule(self) -> bool:
        """Git submodule status getter"""
        return self.__is_submodule
