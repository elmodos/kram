from kram.core.copr import CoprRef, parse_repo_id, parse_search


def test_parse_repo_id():
    assert parse_repo_id("copr:copr.fedorainfracloud.org:wezfurlong:wezterm-nightly") == \
        CoprRef("copr.fedorainfracloud.org", "wezfurlong/wezterm-nightly")
    assert parse_repo_id("copr:copr.fedorainfracloud.org:group_kde:plasma") == \
        CoprRef("copr.fedorainfracloud.org", "@kde/plasma")
    assert parse_repo_id("fedora") is None
    assert parse_repo_id("copr:hub:owner") is None
    assert parse_repo_id("copr:hub:own er:x") is None  # rejected, never reaches the helper
    assert parse_repo_id("copr:hub:-y:x") is None
    assert parse_repo_id("copr:-hub:owner:x") is None


def test_parse_search():
    payload = {"items": [
        {"full_name": "solopasha/hyprland", "description": "Hyprland  and\n friends", "homepage": "",
         "chroot_repos": {"fedora-44-x86_64": "u", "fedora-43-x86_64": "u"}},
        {"full_name": "bad name/x", "chroot_repos": {}},
        {"full_name": "@kde/plasma", "description": None, "chroot_repos": None},
    ]}
    projects = parse_search(payload)
    assert [p.full_name for p in projects] == ["solopasha/hyprland", "@kde/plasma"]
    assert projects[0].description == "Hyprland and friends"
    assert projects[0].has_chroot("44", "x86_64")
    assert not projects[0].has_chroot("45", "x86_64")
    assert projects[1].chroots == ()


def test_rank():
    from kram.core.copr import CoprProject, rank

    def p(name):
        return CoprProject(name, "", "", ())
    projects = [p("apognu/fedora-pkgs"), p("lionheartp/Hyprland"), p("solopasha/hyprland"),
                p("x/hyprland-git"), p("y/my-hyprland-tools"), p("hyprland/extras")]
    assert [x.full_name for x in rank(projects, "hyprland")] == [
        "lionheartp/Hyprland", "solopasha/hyprland", "x/hyprland-git", "y/my-hyprland-tools",
        "hyprland/extras", "apognu/fedora-pkgs"]
    assert rank(projects, "solopasha/hyprland")[0].full_name == "solopasha/hyprland"
