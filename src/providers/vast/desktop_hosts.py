"""Public, read-only host summaries for the desktop; never expose raw API records."""
import json
import math
import sys
import time


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def summarize(offers):
    if not isinstance(offers, list):
        raise ValueError('Invalid offer response')
    result = {}
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        offer_id = offer.get('id')
        price = number(offer.get('dph_total'))
        if type(offer_id) is not int or offer_id <= 0 or price is None:
            continue
        fields = {key: number(offer.get(key)) for key in (
            'machine_id', 'cpu_cores_effective', 'cpu_cores', 'cpu_ghz', 'gpu_ram',
            'cpu_ram', 'disk_space', 'disk_bw', 'inet_down', 'inet_up',
            'reliability', 'direct_port_count', 'inet_down_cost', 'inet_up_cost',
            'storage_cost', 'gpu_max_power', 'gpu_lanes', 'pci_gen')}
        rank = offer.get('_vg')
        fields.update(score=number(rank.get('score')) if isinstance(rank, dict) else None,
                      id=offer_id, gpu_name=str(offer.get('gpu_name', ''))[:80],
                      cpu_name=str(offer.get('cpu_name') or 'Not reported')[:160],
                      disk_name=str(offer.get('disk_name') or 'Not reported')[:160],
                      geolocation=str(offer.get('geolocation') or 'Not reported')[:100],
                      driver_version=str(offer.get('driver_version') or 'Not reported')[:40],
                      verification=str(offer.get('verification') or 'Not reported')[:40],
                      dph_total=price)
        result[offer_id] = fields
    return sorted(result.values(), key=lambda h: (h['dph_total'], h['id']))


if __name__ == '__main__':
    try:
        disk = int(sys.argv[1])
        raw = sys.stdin.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('Offer response too large')
        print(json.dumps(dict(offers=summarize(json.loads(raw)),
                              disk_gb=disk, updated=int(time.time()))))
    except (ValueError, TypeError, IndexError):
        print('Cannot read Vast host offers. Refresh to retry.', file=sys.stderr)
        sys.exit(1)
