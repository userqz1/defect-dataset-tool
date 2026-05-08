"""DetailView segment panes.

Each pane is a standalone ``QWidget`` that sits inside the DetailView
sidebar's ``QStackedWidget``. Panes are purely presentational — they
emit intent signals; the shell (DetailView) wires them to the save
handlers + SampleSet + viewer.

Which panes are instantiated for a given project is decided by
:class:`gui.views.detail_specs.TaskWorkbenchSpec`.
"""
