import unittest

from ssh_wallet.model import Host


class HostNormalizationTest(unittest.TestCase):
    def test_strips_whitespace_from_single_line_fields(self):
        host = Host(name="  nas ", host=" 10.0.0.5\t", user=" kuba ", key_path=" ~/.ssh/id ")

        self.assertEqual(host.name, "nas")
        self.assertEqual(host.host, "10.0.0.5")
        self.assertEqual(host.user, "kuba")
        self.assertEqual(host.key_path, "~/.ssh/id")

    def test_each_new_host_gets_its_own_id(self):
        self.assertNotEqual(Host(name="a", host="a").id, Host(name="a", host="a").id)


class HostValidationTest(unittest.TestCase):
    def test_valid_host_has_no_errors(self):
        self.assertEqual(Host(name="nas", host="10.0.0.5", port=2222, user="kuba").errors(), [])

    def test_empty_name_is_an_error(self):
        self.assertEqual(Host(name="  ", host="10.0.0.5").errors(), ["Název nesmí být prázdný."])

    def test_empty_host_is_an_error(self):
        self.assertEqual(Host(name="nas", host="").errors(), ["Host nesmí být prázdný."])

    def test_host_with_inner_space_is_an_error(self):
        self.assertEqual(Host(name="nas", host="my nas").errors(), ["Host nesmí obsahovat mezery."])

    def test_host_starting_with_dash_is_an_error(self):
        # Would otherwise be parsed by ssh as an option, e.g. -oProxyCommand=...
        self.assertEqual(
            Host(name="x", host="-oProxyCommand=evil").errors(),
            ["Host nesmí začínat pomlčkou."],
        )

    def test_user_starting_with_dash_is_an_error(self):
        self.assertEqual(
            Host(name="x", host="h", user="-oProxyCommand=evil").errors(),
            ["Username nesmí začínat pomlčkou."],
        )

    def test_port_bounds(self):
        for port, valid in [(0, False), (1, True), (22, True), (65535, True), (65536, False)]:
            with self.subTest(port=port):
                errors = Host(name="nas", host="h", port=port).errors()
                self.assertEqual(errors, [] if valid else ["Port musí být v rozsahu 1-65535."])


class HostSubtitleTest(unittest.TestCase):
    def test_default_port_is_shown_too(self):
        self.assertEqual(Host(name="m", host="192.168.1.1", user="admin").subtitle(), "admin@192.168.1.1:22")

    def test_custom_port(self):
        self.assertEqual(Host(name="n", host="nas", user="kuba", port=2222).subtitle(), "kuba@nas:2222")

    def test_without_user(self):
        self.assertEqual(Host(name="n", host="nas").subtitle(), "nas:22")


class HostMatchesTest(unittest.TestCase):
    host = Host(name="Web Prod", host="10.0.0.5", user="deploy", note="Hlavní eshop")

    def test_empty_query_matches(self):
        self.assertTrue(self.host.matches("   "))

    def test_matches_each_field_case_insensitively(self):
        for query in ["web", "PROD", "10.0.0", "Deploy", "ESHOP"]:
            with self.subTest(query=query):
                self.assertTrue(self.host.matches(query))

    def test_non_matching_query(self):
        self.assertFalse(self.host.matches("nas"))

    def test_all_terms_must_match(self):
        self.assertTrue(self.host.matches("prod deploy"))
        self.assertFalse(self.host.matches("prod nas"))


if __name__ == "__main__":
    unittest.main()
