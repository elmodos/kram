# Package cache

Settings → Package Cache… shows what the package caches take, where they are, and cleans them.

![The Package Cache window: dnf's downloaded packages, repository metadata, your user's dnf cache, and 3.3 GB
left behind by Discover and GNOME Software](../screenshots/package-cache.png)

*Each cache with its size and folder. Here the biggest one is not dnf's: Discover left 3.3 GB of offline
updates behind.*

- **DNF: downloaded packages**: left by interrupted transactions and by "download packages only".
- **DNF: repository metadata**: what Kram and dnf know about the available packages. Kram can download it
  again from scratch.
- **DNF: cache of your user**: written by dnf when it runs without root. Kram does not use it.
- **Discover / GNOME Software**: packages PackageKit downloaded for offline updates and never removed.

Next: [Update notifications](update-notifications.md).
