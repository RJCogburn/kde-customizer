#! /bin/bash
# AppImage entry point: CLI subcommands go to `kdec`, everything else opens the GUI.
#   KDE_Customizer.AppImage                     -> GUI
#   KDE_Customizer.AppImage mytheme.toml        -> GUI with that theme
#   KDE_Customizer.AppImage build mytheme.toml  -> CLI
case "${1:-}" in
    new|build|export|apply|layout|check|snapshot|ai|ai-guide|icons|wallpaper|revert|installed|palette|doctor|-h|--help)
        exec {{ python-executable }} -I -m kdecustomizer.cli "$@" ;;
    *)
        exec {{ python-executable }} -I -m kdecustomizer.gui.app "$@" ;;
esac
