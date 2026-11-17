"""The capability index behind Provides searches, and taking requirements apart. No libdnf5."""
from kram.core.capabilities import dependency_names, match

KATE, FIREFOX = ("kate", "x86_64"), ("firefox", "x86_64")
REQUESTS, URLLIB3 = ("python3-requests", "noarch"), ("python3-urllib3", "noarch")
VULKAN, UPPER = ("vulkan-loader", "x86_64"), ("upper", "x86_64")
INDEX = {
    "python3dist(requests)": {REQUESTS},
    "python3dist(urllib3)": {URLLIB3},
    "libvulkan.so.1()(64bit)": {VULKAN},
    "application()": {KATE, FIREFOX},
    "application(org.kde.kate.desktop)": {KATE},
    "Lib": {UPPER},
}


def test_a_plain_word_matches_part_of_a_name():
    assert match(INDEX, "python3dist") == {REQUESTS, URLLIB3}
    assert match(INDEX, "vulkan") == {VULKAN}
    assert match(INDEX, "nothing") == set()


def test_a_glob_matches_whole_names():
    assert match(INDEX, "python3dist(*)") == {REQUESTS, URLLIB3}
    assert match(INDEX, "python3dist([r]*)") == {REQUESTS}
    assert match(INDEX, "application(*.desktop)") == {KATE}
    assert match(INDEX, "vulkan*") == set()  # whole name: it starts with "lib"
    assert match(INDEX, "*vulkan*") == {VULKAN}


def test_case_counts_as_in_libdnf5():
    assert match(INDEX, "Lib") == {UPPER}
    assert UPPER not in match(INDEX, "lib")


def test_plain_requirements_name_one_capability():
    assert dependency_names("python3dist(requests) >= 2.0") == {"python3dist(requests)"}
    assert dependency_names("libc.so.6()(64bit)") == {"libc.so.6()(64bit)"}
    assert dependency_names("bash") == {"bash"}


def test_rich_requirements_name_all_of_theirs_and_keep_their_parentheses():
    assert dependency_names("(python3dist(aiohttp) >= 3.9 with python3dist(aiohttp) < 4)") == {"python3dist(aiohttp)"}
    assert dependency_names("((a or b) and c)") == {"a", "b", "c"}
    assert dependency_names("(kmod(x.ko) if kernel-core unless dkms)") == {"kmod(x.ko)", "kernel-core", "dkms"}
    assert dependency_names("(foo = 1:2.3-4 or bar)") == {"foo", "bar"}
