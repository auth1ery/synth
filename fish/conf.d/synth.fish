# synth: fish integration. Fish loads this file automatically from conf.d.
#
# Customize before it loads (for example in config.fish):
#   set -g synth_bind \ct        key that opens synth from the prompt (default alt-t)
#   set -g synth_bind ''         disable the key binding
#   set -g synth_abbr todo       abbreviation that expands to synth (default st)
#   set -g synth_abbr ''         disable the abbreviation

status is-interactive; or return

set -q synth_bind; or set -g synth_bind \et
set -q synth_abbr; or set -g synth_abbr st

if test -n "$synth_abbr"
    abbr -a $synth_abbr synth
end

if test -n "$synth_bind"
    bind $synth_bind _synth_launch
    bind -M insert $synth_bind _synth_launch 2>/dev/null
end
