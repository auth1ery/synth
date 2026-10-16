function synth --description 'synth. a fullscreen terminal todo list'
    set -l script $HOME/.local/share/synth/synth.py
    set -q SYNTH_BIN; and set script $SYNTH_BIN
    if not test -f $script
        echo "synth: cannot find $script (run install.fish, or set SYNTH_BIN)" >&2
        return 127
    end
    command python3 $script $argv
end
