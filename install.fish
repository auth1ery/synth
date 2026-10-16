#!/usr/bin/env fish
# Install synth for the fish shell.
#   ./install.fish              install
#   ./install.fish --uninstall  remove everything this script installed
#   curl -fsSL https://auth1ery.github.io/synth/install.fish | fish   install without cloning

set -l here (dirname (status filename))
set -l share $HOME/.local/share/synth
set -l fishdir (set -q XDG_CONFIG_HOME; and echo $XDG_CONFIG_HOME; or echo $HOME/.config)/fish
set -l bindir $HOME/.local/bin

if contains -- --uninstall $argv
    rm -f $share/synth.py $bindir/synth
    rm -f $fishdir/conf.d/synth.fish $fishdir/completions/synth.fish
    for f in synth _synth_launch synth_count synth_due synth_habits synth_tracking
        rm -f $fishdir/functions/$f.fish
    end
    echo "synth removed. Your todos and config were left in place:"
    echo "  $share/todos.json"
    echo "  $HOME/.config/synth/config.toml"
    exit 0
end

if not command -q python3
    echo "synth needs python3" >&2
    exit 1
end
if not python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))'
    echo "synth needs python 3.8 or newer (3.11+ for config.toml support)" >&2
    exit 1
end

# Run from a pipe (curl | fish) or outside a checkout: fetch the repo first.
set -l tmp ""
if not test -f $here/synth.py
    if not command -q curl; or not command -q tar
        echo "synth: no local files found and curl or tar is missing. Clone the repo and run ./install.fish" >&2
        exit 1
    end
    set tmp (mktemp -d)
    echo "downloading synth..."
    if not curl -fsSL https://github.com/auth1ery/synth/archive/refs/heads/master.tar.gz | tar -xz -C $tmp --strip-components=1
        echo "synth: download failed" >&2
        rm -rf $tmp
        exit 1
    end
    set here $tmp
end

mkdir -p $share $bindir $fishdir/conf.d $fishdir/functions $fishdir/completions
install -m 755 $here/synth.py $share/synth.py
ln -sf $share/synth.py $bindir/synth
cp $here/fish/conf.d/*.fish $fishdir/conf.d/
cp $here/fish/functions/*.fish $fishdir/functions/
cp $here/fish/completions/*.fish $fishdir/completions/

test -n "$tmp"; and rm -rf $tmp

echo "synth installed."
echo "  open a new fish session, then run: synth"
echo "  shortcuts: st (abbreviation), alt-t (key binding)"
echo "  config:    $HOME/.config/synth/config.toml (created on first run)"