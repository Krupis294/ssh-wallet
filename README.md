# SSH Wallet

Jednoduchý správce SSH připojení pro Linux (GTK4 + libadwaita). Hosty si uložíš
do seznamu, vybereš jeden a otevře se nové okno [kitty](https://sw.kovidgoyal.net/kitty/)
s připojeným `ssh`.

- vyhledávání v názvu, hostu, usernamu i poznámce; `Enter` připojí první shodu
- hesla jsou v gnome-keyring (Secret Service), ne v souboru; při připojení je
  ssh převezme automaticky přes `SSH_ASKPASS`, heslo se neobjeví v příkazové
  řádce ani v proměnných prostředí
- volitelně vlastní SSH klíč (`ssh -i`) a poznámka
- `~/.ssh/config` zůstává nedotčený a ssh ho dál používá

## Požadavky

Arch Linux: `python` (3.11+), `python-gobject`, `gtk4`, `libadwaita`, `libsecret`,
`openssh` (8.4+), `kitty` a běžící Secret Service (gnome-keyring nebo KeePassXC).

## Instalace

```sh
./install.sh
```

Vytvoří `~/.local/bin/ssh-wallet` (symlink do tohoto adresáře) a položku
v nabídce aplikací. Aplikace běží přímo z tohoto adresáře, takže ho po instalaci
nepřesouvej (případně spusť `install.sh` znovu).

## Ovládání

| Klávesa  | Akce                          |
|----------|-------------------------------|
| psaní    | hledání                       |
| ↑ / ↓    | výběr v seznamu               |
| Enter    | připojit                      |
| Ctrl+N   | nový host                     |
| Ctrl+E   | upravit vybraný host          |
| Delete   | smazat vybraný host (v seznamu) |
| Ctrl+F   | skok do hledání               |
| Esc      | vymazat hledání               |
| Ctrl+Q   | konec                         |

## Jump server a tunely

- **Jump server:** ve formuláři hostu vyber jiný uložený host. Připojení
  (kitty i tunel) pak vede přes něj jako `ProxyCommand`, takže jump použije
  svůj vlastní port, klíč i uložené heslo; askpass pozná, o které heslo se
  ssh ptá.
- **Přesměrování portů:** ve formuláři přidej řádky `L` (port u tebe vede na
  cíl za serverem, např. `5901 → localhost:5901` pro VNC) nebo `R` (port na
  serveru vede na cíl u tebe).
- **Tunel:** host s přesměrováním má v seznamu přepínač *Tunel*. Zapnutí spustí
  na pozadí `ssh -N` bez terminálu, vypnutí ho ukončí. Když tunel spadne
  (obsazený port, neznámý otisk hostu, odmítnuté heslo), přepínač se vrátí
  a ukáže se důvod. Tunely končí se zavřením aplikace, ssh v kitty běží dál.
  Bez terminálu se nedá nic doptat, takže tunel potřebuje uložené heslo nebo
  klíč a hosta, ke kterému ses už jednou připojil přes *Připojit*.

## Rofi

`ssh-wallet-rofi` je rychlý výběr hostu přes rofi: napíšeš kus názvu, adresy
nebo poznámky, Enter a otevře se kitty se ssh (hesla a askpass fungují stejně
jako v GTK aplikaci). Poslední položka `Otevřít SSH Wallet` spustí GTK okno
pro přidání a úpravy.

```sh
ssh-wallet-rofi                  # vlastní motiv (data/ssh-wallet.rasi)
ssh-wallet-rofi --system-theme   # tvůj rofi config
```

Klávesová zkratka v Hyprlandu (`~/.config/hypr/UserConfigs/UserKeybinds.conf`):

```
unbind = $mainMod, S  # replaces web search (configs/Keybinds.conf)
bindd = $mainMod, S, ssh wallet, exec, $HOME/.local/bin/ssh-wallet-rofi
```

## Vzhled

Tmavý terminálový styl sladěný s kitty: písmo FantasqueSansM Nerd Font Mono
(záložně Fira Code / monospace), téměř černé pozadí a jediný zelený akcent.
Barvy, písmo i zaoblení jsou v [`ssh_wallet/ui/style.css`](ssh_wallet/ui/style.css)
(proměnné nahoře v `:root`), takže se dají snadno přebarvit.

## Jak to funguje

- Hosty: `~/.config/ssh-wallet/hosts.json` (práva `0600`, atomický zápis).
  Nečitelný soubor se nepřepíše, ale přesune na `hosts.json.bak-<čas>`.
- Připojení: `kitty --title=<název> -o term=xterm-256color sh -c <wrapper> ssh -p <port> [-i <klíč>] -- <user>@<host>`.
  Když ssh skončí kódem 255 (spojení selhalo), okno počká na Enter, ať je chyba vidět.
- Hesla: u hostů s heslem se nastaví `SSH_ASKPASS=bin/ssh-wallet-askpass`
  a `SSH_ASKPASS_REQUIRE=force`. Helper odpoví na první dotaz na heslo
  uloženým heslem; když server heslo odmítne, zeptá se ručně v terminálu.
  Ostatní dotazy (otisk hostu `yes/no`, passphrase klíče, 2FA) jdou vždy
  normálně do terminálu.

## Testy

```sh
python -m unittest discover -s tests -t .
```

UI testy potřebují grafický displej (jinak se přeskočí). Testy proti
skutečnému keyringu běží jen s `SSH_WALLET_KEYRING_TESTS=1` a používají
oddělené testové schéma.
