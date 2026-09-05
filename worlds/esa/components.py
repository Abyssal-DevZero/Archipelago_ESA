"""Launcher registration.

Nothing to register yet — the client does not exist. When it does, this is
where it goes:

    from worlds.LauncherComponents import Component, Type, components, launch_subprocess

    def launch_client(*args):
        from .client import launch
        launch_subprocess(launch, name="ESAClient", args=args)

    components.append(Component("ESA Client", func=launch_client,
                                component_type=Type.CLIENT))
"""
