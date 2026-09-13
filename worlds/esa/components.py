from worlds.LauncherComponents import Component, Type, components, launch as launch_component

    def launch_client(*args):
        from .client.client import launch
        launch_component(launch, name="ESAClient", args=args)
        
components.append(Component(
    "ESA Client",
    func=launch_client,
    component_type=Type.CLIENT,
    game_name="Environmental Station Alpha",
    supports_uri=True,
    description="Start this client first, before starting the game",
))
