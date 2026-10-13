import unittest

from ssh_wallet.model import Forward, Host


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

    def test_ipv6_address_is_bracketed_so_the_port_stays_readable(self):
        host = Host(name="p", host="2001:718:1001:2cf::e429", user="student")

        self.assertEqual(host.subtitle(), "student@[2001:718:1001:2cf::e429]:22")
        self.assertEqual(host.destination(), "student@2001:718:1001:2cf::e429")


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



class ForwardTest(unittest.TestCase):
    def test_local_spec(self):
        self.assertEqual(Forward("L", 5901, "localhost", 5901).spec(), "5901:localhost:5901")

    def test_ipv6_destination_is_bracketed(self):
        self.assertEqual(Forward("R", 8080, "fe80::1", 80).spec(), "8080:[fe80::1]:80")

    def test_describe(self):
        self.assertEqual(Forward("L", 5901, "localhost", 5901).describe(), "L 5901 → localhost:5901")
        self.assertEqual(Forward("R", 8080, "fe80::1", 80).describe(), "R 8080 → [fe80::1]:80")

    def test_valid_forward_has_no_errors(self):
        self.assertEqual(Forward("L", 1, "db.local", 65535).errors(), [])

    def test_errors(self):
        cases = [
            (Forward("D", 1080, "localhost", 1), ["Typ musí být L nebo R."]),
            (Forward("L", 0, "localhost", 22), ["Port musí být v rozsahu 1-65535."]),
            (Forward("L", 22, "localhost", 70000), ["Cílový port musí být v rozsahu 1-65535."]),
            (Forward("L", 22, " ", 22), ["Cílový host nesmí být prázdný."]),
            (Forward("L", 22, "a b", 22), ["Cílový host nesmí obsahovat mezery."]),
        ]
        for forward, expected in cases:
            with self.subTest(forward=forward):
                self.assertEqual(forward.errors(), expected)


class HostJumpAndForwardsTest(unittest.TestCase):
    def test_defaults(self):
        host = Host(name="n", host="h")

        self.assertEqual((host.jump_id, host.forwards), ("", []))

    def test_forward_errors_are_numbered(self):
        host = Host(name="n", host="h", forwards=[Forward("L", 1, "x", 1), Forward("L", 0, "x", 1)])

        self.assertEqual(host.errors(), ["Přesměrování 2: Port musí být v rozsahu 1-65535."])

    def test_host_cannot_jump_through_itself(self):
        host = Host(name="n", host="h", id="id-1", jump_id="id-1")

        self.assertEqual(host.errors(), ["Host nemůže být svým vlastním jump serverem."])


if __name__ == "__main__":
    unittest.main()
