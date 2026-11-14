# Installing a downloaded .rpm file

Open a file with File → Open Package File…, drop it on the Kram window, or choose "Open with Kram" in the file
manager. `kram ~/Downloads/some-package.rpm` on the command line opens only the installer for that file.

![The Install Package File window for agave-nf: not installed yet, signed with an unknown key, in no
repository, runs scripts as root](../screenshots/install-file.png)

*Before installing, Kram says what it will do and what to watch out for: here a font package signed with a
key this system does not know, which no repository has.*

Before anything happens Kram shows:

- whether the file installs, upgrades, downgrades or reinstalls a package;
- who signed it, or that nobody did;
- whether a repository has the same package, perhaps in a newer version, so you can take that one instead;
- the scripts it runs as root when it is installed or removed (the Scripts tab);
- what satisfies each of its dependencies;
- its description, files and changelog, like any other package.

![The same window for a package that is already installed: reinstall, the installed files are intact, and
every requirement with the package that provides it](../screenshots/install-dependencies.png)

*A reinstall first checks the installed files (`rpm -V`). Every requirement shows the installed package that
satisfies it.*

The helper installs exactly the file you saw: it checks its SHA-256, and reads it with your own permissions,
not root's.

Next: [Repositories and COPR](repositories.md).
