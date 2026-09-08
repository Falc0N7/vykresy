"""Testy pro config.py — hardware detekce a profily."""
import config


def test_get_hardware_specs():
    specs = config.get_hardware_specs()
    assert "cpu_count" in specs
    assert "ram_gb" in specs
    assert "has_gpu" in specs
    assert specs["cpu_count"] >= 1
    assert specs["ram_gb"] > 0


def test_get_dynamic_hardware_profiles():
    profiles = config.get_dynamic_hardware_profiles()
    assert "turbo" in profiles
    assert "eco" in profiles
    for key in ("turbo", "eco"):
        p = profiles[key]
        assert "cpu_threads" in p
        assert "max_image_dim" in p
        assert "io_workers" in p
        assert p["cpu_threads"] >= 1


def test_get_detected_devices():
    devs = config.get_detected_devices()
    # vždy alespoň CPU
    assert any(d[0] == "cpu" for d in devs)
    assert len(devs) >= 1
