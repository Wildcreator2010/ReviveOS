def test_imports():
    import revive_agents
    import revive_api
    import revive_cli
    import revive_core

    assert all((revive_core, revive_cli, revive_agents, revive_api))
