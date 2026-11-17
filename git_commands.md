Bro, use **SSH** for GitLab authentication. Set it up once, then use feature branches and merge requests for collaboration.

These examples assume `gitlab.com` and a default branch named `main`. Replace those if your team uses something else.

**1. Install Git and SSH**

Run the command for your Linux distribution:

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install git openssh-client

# Fedora
sudo dnf install git openssh-clients

# Arch
sudo pacman -S git openssh
```

Set your commit identity using your GitLab email:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

**2. Connect your machine to GitLab**

First check for an existing key:

```bash
ls -l ~/.ssh/*.pub
```

If you already have `id_ed25519.pub`, you can reuse it. Otherwise generate one:

```bash
ssh-keygen -t ed25519 -C "you@example.com"
```

Accept the default location and set a passphrase. **Don’t overwrite an existing key.**

Load the key and display its public part:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Copy that output into **GitLab → Edit profile → Access → SSH keys → Add new key**. Only copy the `.pub` file; the other file is private.

Test the connection:

```bash
ssh -T git@gitlab.com
```

On the first connection, verify the displayed host fingerprint against GitLab’s documentation before accepting. Success looks like `Welcome to GitLab, @username!`. [GitLab SSH setup](https://docs.gitlab.com/user/ssh/)

**3. Clone your team’s repository**

Copy the project’s **Code → Clone with SSH** URL:

```bash
git clone git@gitlab.com:YOUR-GROUP/YOUR-PROJECT.git
cd YOUR-PROJECT
```

If you already cloned using HTTPS, switch the existing repository to SSH:

```bash
git remote set-url origin git@gitlab.com:YOUR-GROUP/YOUR-PROJECT.git
git remote -v
```

Your GitLab account must also have permission to access and push to the project.

**4. Everyday collaboration command flow**

Start each task from the latest `main`:

```bash
git switch main
git pull --ff-only origin main

# Create a branch for this task
git switch -c feature/login-page
```

Make your changes, then review and commit:

```bash
git status
git diff

# Replace these with the files you changed
git add path/to/file1 path/to/file2

git diff --staged
git commit -m "Add login page"

# First push: connect your local branch to its remote branch
git push -u origin feature/login-page
```

Open GitLab and create a **Merge Request** from `feature/login-page` into `main`. Ask a teammate to review it and let the project’s checks pass before merging.

For further changes on that same branch:

```bash
git add path/to/changed-file
git commit -m "Address review feedback"
git push
```

**5. Bring teammates’ changes into your branch**

With your own changes committed, run:

```bash
git fetch origin
git merge origin/main
git push
```

If there are conflicts, Git pauses the merge. Open the listed files, resolve the conflicting sections, remove the conflict markers, then:

```bash
git add path/to/resolved-file
git commit
git push
```

To cancel an in-progress merge:

```bash
git merge --abort
```

Some teams require rebasing instead of merging `main`; follow your team’s convention. Rebasing a published branch rewrites its history and can require `--force-with-lease`, so coordinate with anyone sharing that branch. [GitLab rebase guidance](https://docs.gitlab.com/topics/git/git_rebase/)

**6. After your merge request is merged**

```bash
git switch main
git pull --ff-only origin main

# Delete the finished local branch
git branch -d feature/login-page
git fetch --prune
```

If deletion is refused after a squash merge, confirm your work is present in `main` before forcing deletion.

The daily flow is: **update main → create branch → edit → commit → push → merge request → review → merge**. Keep secrets out of commits, and avoid force-pushing shared branches.