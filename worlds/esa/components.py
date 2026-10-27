from worlds.LauncherComponents import Component, Type, components, icon_paths, launch as launch_component

def launch_client(*args):
    from .client.client import launch
    launch_component(launch, name="ESAClient", args=args)
    
icon_paths["esa"] = f"ap:{__package__}/data/esa_icon.png"

components.append(Component(
    "ESA Client",
    func=launch_client,
    component_type=Type.CLIENT,
    icon="esa",
    game_name="Environmental Station Alpha",
    supports_uri=True,
    description="Client for Environmental Station Alpha",
))
