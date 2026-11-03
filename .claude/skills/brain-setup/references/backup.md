# Online backup

A private copy on GitHub, made with the person, who signs in themselves.

1. `gh --version`. Missing: on a Mac with Homebrew, `brew install gh`; otherwise walk them through
   the download from cli.github.com, or skip to step 4.
2. `gh auth login --hostname github.com --git-protocol https --web`: it prints a one-time code and a
   web address. Give both to the person; they sign in in their browser. Never ask for a password.
3. `gh repo create "<name>" --private --source . --remote origin --push`. Then `brain-sync` pushes
   from now on whenever they ask.
4. Without `gh`: walk them through github.com → New repository: a name, **Private**, and **no**
   README, licence or .gitignore (any of those makes the first push fail). Take its address, run
   `git remote add origin <address>` and `git push -u origin main`; git opens the browser to sign in.
5. Nested project folders with their own history are not part of this backup: name them, and offer
   to do the same for each, on a yes.
