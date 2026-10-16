#!/usr/bin/env fish
# Install synth for the fish shell.
#   ./install.fish              install
#   ./install.fish --uninstall  remove everything this script installed

set -l here (dirname (status filename))
set -l share $HOME/.local/share/synth
set -l fishdir (set -q XDG_CONFIG_HOME; and echo $XDG_CONFIG_HOME; or echo $HOME/.config)/fish
set -l bindir $HOME/.local/bin

if contains -- --uninstall $argv
    rm -f $share/synth.py $bindir/synth
    for f in $here/fish/conf.d/*.fish
        rm -f $fishdir/conf.d/(basename $f)
    end
    for f in $here/fish/functions/*.fish
        rm -f $fishdir/functions/(basename $f)
    end
    for f in $here/fish/completions/*.fish
        rm -f $fishdir/completions/(basename $f)
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

mkdir -p $share $bindir $fishdir/conf.d $fishdir/functions $fishdir/completions
install -m 755 $here/synth.py $share/synth.py
ln -sf $share/synth.py $bindir/synth
cp $here/fish/conf.d/*.fish $fishdir/conf.d/
cp $here/fish/functions/*.fish $fishdir/functions/
cp $here/fish/completions/*.fish $fishdir/completions/

echo "synth installed."
echo "  open a new fish session, then run: synth"
echo "  shortcuts: st (abbreviation), alt-t (key binding)"
echo "  config:    $HOME/.config/synth/config.toml (created on first run)"
