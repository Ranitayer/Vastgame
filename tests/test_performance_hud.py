from support import cli_source
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/runtime'))
sys.path.insert(0, str(ROOT / 'src/client'))
import telemetry
spec = importlib.util.spec_from_file_location('performance_hud', ROOT/'src/client/performance_hud.py')
hud = importlib.util.module_from_spec(spec); spec.loader.exec_module(hud)

STATS = '''Video stream: 2944x1840 90.00 FPS (Codec: HEVC)
Bitrate: 45.2 Mbps, Peak (10s): 48.0
Incoming frame rate from network: 90.00 FPS
Decoding frame rate: 90.00 FPS
Rendering frame rate: 89.95 FPS
Host processing latency min/max/average: 1.0/5.0/2.0 ms
Frames dropped by your network connection: 0.10%
Frames dropped due to network jitter: 0.20%
Average network latency: 28 ms (variance: 3 ms)
Average decoding time: 0.90 ms
Average frame queue delay: 0.50 ms
Average rendering time (including monitor V-sync latency): 4.00 ms
'''


def perfect():
    return dict(game_fps=90, frametime_ms=11.1, stream_fps=90, decode_ms=1, rtt_ms=15,
                jitter_ms=1, network_drop_pct=0, probe_loss_pct=0, host_processing_ms=2,
                gpu_pct=85, gpu_temp_c=70, cpu_pct=40, ram_used_gib=12, ram_total_gib=64,
                vram_used_mib=8000, vram_total_mib=16000, codec='HEVC', bitrate_mbps=45,
                resolution='2944x1840', route='direct')


class MetricsTests(unittest.TestCase):
    def test_metrics_log_rotation_keeps_one_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'metrics.jsonl'
            previous = path.with_name(path.name+'.1')
            previous.write_text('obsolete')
            with path.open('wb') as output:
                output.truncate(16*1024**2)
            hud.append_metrics(path, {'updated': 1})
            self.assertEqual(previous.stat().st_size, 16*1024**2)
            self.assertEqual(json.loads(path.read_text()), {'updated': 1})

    def test_client_stats_are_real_stream_not_game_fps(self):
        m = hud.parse_moonlight(STATS)
        self.assertEqual(m['stream_fps'], 89.95)
        self.assertEqual(m['resolution'], '2944x1840')
        self.assertEqual(m['codec'], 'HEVC')
        self.assertEqual(m['host_processing_ms'], 2)
        self.assertNotIn('game_fps', m)
        self.assertNotIn('encode_ms', m)
        self.assertEqual(m['network_drop_pct'], .1)
        self.assertEqual(m['decode_ms'], .9)

    def test_unknown_and_na_stats_stay_unknown(self):
        self.assertEqual(hud.parse_moonlight('Average network latency: N/A'), {})
        self.assertIsNone(hud.assess({},90)['score'])

    def test_complete_ideal_measurements_can_reach_100(self):
        self.assertEqual(hud.assess(perfect(),90)['score'],100)
        self.assertEqual(hud.assess(perfect(),90)['coverage'],100)

    def test_missing_critical_measurement_cannot_reach_100(self):
        m=perfect(); del m['game_fps']
        quality=hud.assess(m,90)
        self.assertLess(quality['score'],100)
        self.assertLess(quality['coverage'],100)
        m=perfect(); m['route']='unknown'
        self.assertLess(hud.assess(m,90)['score'],100)

    def test_ranking_uses_recent_matching_context(self):
        ranking=(ROOT/'src/providers/vast/rank.jq').read_text()
        code=ranking.split('def performance_bonus($h):',1)[1].split('def tier($s):',1)[0]
        expression='def performance_bonus($h):'+code+'performance_bonus($h)'
        import copy
        base=dict(samples=30,updated=time.time(),delivery_score=100,game_delivery_score=100,
                  game_id='fixture',resolution='2944x1840',target_fps=90)
        for changes,expected in [({},6),({'game_id':'other'},4),({'samples':2},0),({'updated':0},0),
                                 ({'delivery_score':30,'game_delivery_score':40},-12)]:
            summary=copy.copy(base); summary.update(changes)
            result=subprocess.check_output(['jq','--argjson','h',json.dumps({'machine:123':{'performance':summary}}),
                '--arg','selected_game','fixture','--arg','native_resolution','2944x1840',
                '--argjson','native_fps','90',expression],input='{"machine_id":123}',text=True)
            self.assertEqual(int(result),expected)

    def test_slow_decode_identified(self):
        m=perfect(); m['decode_ms']=18
        self.assertIn('client-decode',hud.assess(m,90)['bottleneck'])

    def test_network_not_gpu_when_game_meets_target(self):
        m=perfect(); m.update(gpu_pct=100, rtt_ms=120)
        self.assertIn('network',hud.assess(m,90)['bottleneck'])

    def test_gpu_and_single_core_limit(self):
        m=perfect(); m.update(game_fps=40, frametime_ms=25, gpu_pct=99)
        self.assertIn('GPU',hud.assess(m,90)['bottleneck'])
        m.update(gpu_pct=50, cpu_max_core_pct=99)
        self.assertIn('CPU',hud.assess(m,90)['bottleneck'])

    def test_relay_and_frame_drops_reduce_quality(self):
        m=perfect(); m['route']='relayed'
        self.assertLess(hud.assess(m,90)['score'],100)
        m.update(route='direct',network_drop_pct=3)
        self.assertEqual(hud.assess(m,90)['score'],0)

    def test_full_hud_is_dense_color_coded_and_labels_probe_loss(self):
        lines=hud.hud_lines(perfect(),hud.assess(perfect(),90),90)
        self.assertEqual(len(lines),11)
        self.assertTrue(all(line.startswith('#') and line[7]=='|' for line in lines))
        self.assertIn('probe loss','\n'.join(lines))
        self.assertIn('Game source: MangoHud','\n'.join(lines))
        self.assertIn('RAM','\n'.join(lines))
        self.assertIn('VRAM','\n'.join(lines))
        m=perfect(); m['decode_ms']=20
        quality=hud.assess(m,90)
        decoder=next(line for line in hud.hud_lines(m,quality,90) if '|Decode ' in line)
        self.assertTrue(decoder.startswith('#ff7979|'))

    def test_managed_mango_starts_hidden_logging_for_only_its_launch(self):
        from unittest.mock import MagicMock, patch
        with tempfile.TemporaryDirectory() as tmp:
            unix=Path(tmp)/'unix'; unix.write_text('header\n0 0 0 0 0 0 0 @vastgame-current-123\n0 0 0 0 0 0 0 @vastgame-old-456\n')
            client=MagicMock(); connected=set()
            with patch.object(telemetry.socket,'socket',return_value=client):
                telemetry.start_mango_logging('vastgame-current-',connected,unix)
                telemetry.start_mango_logging('vastgame-current-',connected,unix)
            connection=client.__enter__.return_value
            connection.connect.assert_called_once_with('\0vastgame-current-123')
            connection.sendall.assert_called_once_with(b':logging=1;')

    def test_partial_csv_rows_never_become_game_fps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'Game.exe_2026.csv'
            source.write_text('cpu_load,frametime,fps,gpu_power\n20,11,90,150\n20,1,999,999')
            sample=telemetry.mango_sample(root,'Game.exe',0)
            self.assertEqual(sample['game_fps'],90)
            self.assertEqual(sample['gpu_power_w'],150)

    def test_vm_packet_binding_and_bad_numbers_cannot_poison_hud(self):
        meta=dict(game_id='fixture',session_id='current')
        vm=dict(meta,updated=100,game_fps=90,frametime_ms=11.1,game_metrics_source='MangoHud')
        metrics={}
        self.assertTrue(hud.merge_vm_metrics(metrics,vm,meta,now=101))
        self.assertEqual(metrics['game_fps'],90)
        for bad in (dict(vm,session_id='old'),dict(vm,updated=90),dict(vm,updated='bad')):
            self.assertFalse(hud.merge_vm_metrics({},bad,meta,now=101))
        bad=dict(vm,game_fps=float('nan'),gpu_pct=-1)
        metrics={}; hud.merge_vm_metrics(metrics,bad,meta,now=101)
        self.assertNotIn('game_fps',metrics); self.assertNotIn('gpu_pct',metrics)

    def test_vm_feed_keeps_brief_gaps_and_labels_older_samples_without_scoring_them(self):
        meta=dict(game_id='fixture',session_id='current')
        feed=hud.VMFeed('100.64.0.1',meta,'unused')
        packet=dict(meta,updated=100,game_fps=90,frametime_ms=11.1,gpu_pct=80)
        self.assertTrue(feed.accept(packet,now=101))
        self.assertFalse(feed.accept(dict(packet,session_id='other'),now=101))
        live,display=feed.views(now=105)
        self.assertEqual(live['game_fps'],90)
        live,display=feed.views(now=109)
        self.assertEqual(live,{})
        self.assertEqual(display['game_fps'],90)
        self.assertEqual(display['game_metrics_status'],'delayed')
        self.assertIn('9s ago',display['game_metrics_note'])
        self.assertNotIn('Game performance',hud.assess(live,90)['components'])
        self.assertNotIn('game_fps',feed.views(now=131)[1])

    def test_collector_uses_isolated_folders_and_preserves_actual_game_fps(self):
        from unittest.mock import patch, Mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'session.json').write_text(json.dumps(dict(session_id='session')))
            with patch.object(telemetry.Path,'home',return_value=root):
                first=telemetry.Collector('fixture','Game.exe',root)
                second=telemetry.Collector('fixture','Game.exe',root)
            self.assertNotEqual(first.folder,second.folder)
            (first.folder/'Game.exe_2026.csv').write_text('fps,frametime,cpu_load\n45,22.2,20\n')
            with patch.object(telemetry,'start_mango_logging'), patch.object(telemetry.subprocess,'run',return_value=Mock(stdout='98,1024,24576,65\n')):
                metrics=first.sample()
            self.assertEqual(metrics['game_fps'],45)
            self.assertEqual(metrics['frametime_ms'],22.2)
            self.assertEqual(metrics['gpu_pct'],98)
            self.assertEqual(metrics['game_metrics_status'],'live')

    def test_game_csv_matches_exe_and_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); now=time.time()
            source=root/'PRAGMATA_2026.csv'
            source.write_text('os,cpu,gpu\nLinux,CPU,GPU\nfps,frametime,cpu_load\n90,11.11,20\n')
            (root/'OtherGame_2026.csv').write_text('fps,frametime,cpu_load\n999,1,1\n')
            now=time.time()
            m=telemetry.mango_sample(root,'PRAGMATA.exe',now-1,now)
            self.assertEqual(m['game_fps'],90)
            self.assertEqual(m['frametime_ms'],11.11)
            self.assertEqual(telemetry.mango_sample(root,'PRAGMATA.exe',now-1,now+10),{})

    def test_wine_named_game_csv_is_game_fps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'wine-SLASHER-Win64-Shipping_2026.csv').write_text('fps,frametime\n70,14.2\n')
            (root/'wine-EpicWebHelper_2026.csv').write_text('fps,frametime\n999,1\n')
            sample=telemetry.mango_sample(root,'SLASHER-Win64-Shipping.exe',0)
            self.assertEqual(sample['game_fps'],70)

    def test_launcher_child_renderer_supplies_game_fps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); proc=root/'proc'; (proc/'123').mkdir(parents=True)
            (proc/'124').mkdir()
            (proc/'123'/'cmdline').write_bytes(b'Z:\\games\\expedition-33\\Sandfall\\Binaries\\Win64\\Sandfall-Win64-Shipping.exe\0')
            (proc/'124'/'cmdline').write_bytes(b'Z:\\games\\expedition-33\\Engine\\Binaries\\Win64\\EpicWebHelper.exe\0')
            names=telemetry.running_game_executables('expedition-33',proc)
            self.assertEqual(names,{'Sandfall-Win64-Shipping.exe'})
            (root/'wine-Sandfall-Win64-Shipping_2026.csv').write_text('fps,frametime\n74,13.5\n')
            (root/'wine-EpicWebHelper_2026.csv').write_text('fps,frametime\n999,1\n')
            sample=telemetry.mango_sample(root,'Expedition33_Steam.exe',0,related=names)
            self.assertEqual(sample['game_fps'],74)

    def test_stream_menu_saves_valid_preferences_without_dropping_other_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); settings=root/'stream.json'
            settings.write_text(json.dumps({'resolution':'native','fps':90,
                'moonlight_options':{'performance-overlay':True,'frame-pacing':False}}))
            (root/'menu.request').write_text('1920x1200|60|30|HEVC|true|false\n')
            hud.apply_menu_request(root,settings)
            saved=json.loads(settings.read_text())
            self.assertEqual((saved['resolution'],saved['fps'],saved['bitrate_mbps']),('1920x1200',60,30))
            self.assertTrue(saved['moonlight_options']['performance-overlay'])
            self.assertFalse(saved['moonlight_options']['frame-pacing'])
            self.assertEqual((root/'menu.status').read_text(),'Saved · reconnect to apply')
            (root/'menu.request').write_text('0x0|60|30|HEVC|true|false\n')
            hud.apply_menu_request(root,settings)
            self.assertEqual(json.loads(settings.read_text()),saved)
            self.assertEqual((root/'menu.status').read_text(),'Could not save stream settings')

    def test_invalid_csv_and_old_session_not_fps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'PRAGMATA.exe_2026.csv'
            source.write_text('fps,frametime,cpu_load\nNaN,Infinity,0\n')
            self.assertEqual(telemetry.mango_sample(root,'PRAGMATA.exe',0),{})
            source.write_text('fps,frametime,cpu_load\n90,11,0\n')
            self.assertEqual(telemetry.mango_sample(root,'PRAGMATA.exe',time.time()+100),{})

    def test_history_preserves_route_and_excludes_client_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'host_history.json'
            path.write_text(json.dumps({'machine:123':{'passes':3,'restore_mbps':500}}))
            m=perfect(); m['decode_ms']=20
            q=hud.assess(m,90)
            samples=[dict(metrics=m,quality=q)]*30
            meta=dict(machine_id=123,game_id='fixture',session_key='one',target_fps=90)
            hud.save_history(path,meta,samples)
            hud.save_history(path,meta,samples)
            result=json.loads(path.read_text())['machine:123']
            self.assertEqual(result['passes'],3)
            self.assertEqual(result['restore_mbps'],500)
            self.assertEqual(len(result['performance_sessions']),1)
            self.assertEqual(result['performance']['delivery_score'],100)
            self.assertLess(result['performance']['feel'],100)

    def test_short_or_unmeasured_sessions_do_not_train_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'host_history.json'
            hud.save_history(path,dict(machine_id=123),[dict(metrics={},quality={})]*60)
            self.assertFalse(path.exists())

    def test_finite_nonnegative_numbers_only(self):
        for value in ['NaN','Infinity','-1',None,'N/A']:
            self.assertIsNone(telemetry.number(value))

    @unittest.skipUnless(shutil.which('g++') and Path('/usr/share/fonts/TTF/DejaVuSans.ttf').exists(),'Native SDL test dependencies unavailable')
    def test_real_sdl_bridge_transparent_full_stats_and_toggle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'hud.txt').write_text('\n'.join(hud.hud_lines(perfect(),hud.assess(perfect(),90),90)))
            (root/'stats.txt').write_text(STATS)
            harness=root/'test.cpp'
            harness.write_text(r'''
#include <SDL.h>
#include <SDL_ttf.h>
#include <fstream>
#include <sstream>
#include <cassert>
int main(int argc,char** argv) {
    assert(SDL_Init(SDL_INIT_VIDEO)==0); assert(TTF_Init()==0);
    auto font=TTF_OpenFont("/usr/share/fonts/TTF/DejaVuSans.ttf",20); assert(font);
    std::ifstream input(std::string(argv[1])+"/stats.txt"); std::stringstream text; text<<input.rdbuf();
    auto render=[&]() { return TTF_RenderUTF8_Blended_Wrapped(font,text.str().c_str(),{255,255,255,255},1024); };
    TTF_SetFontOutline(font,4);
    auto outline=render(); assert(outline);
    for(int y=0;y<outline->h;y++) for(int x=0;x<outline->w;x++) {
      Uint8 r,g,b,a; auto pixel=((Uint32*)((char*)outline->pixels+y*outline->pitch))[x];
      SDL_GetRGBA(pixel,outline->format,&r,&g,&b,&a); assert(a==0);
    }
    SDL_FreeSurface(outline); TTF_SetFontOutline(font,0);
    auto panel=render(); assert(panel && panel->w>300 && panel->h>150 && panel->h<250);
    Uint8 r,g,b,a; SDL_GetRGBA(((Uint32*)panel->pixels)[0],panel->format,&r,&g,&b,&a); assert(a==0);
    SDL_SaveBMP(panel,(std::string(argv[1])+"/preview.bmp").c_str()); SDL_FreeSurface(panel);
    auto key=[&](SDL_Keycode code,int mods=KMOD_LCTRL|KMOD_LALT|KMOD_LSHIFT) {
      SDL_Event e{}; e.type=SDL_KEYDOWN; e.key.keysym.sym=code;
      e.key.keysym.mod=mods; SDL_PushEvent(&e); SDL_PollEvent(&e); };
    key(SDLK_h); auto hidden=render(); assert(hidden && hidden->w==1 && hidden->h==1); SDL_FreeSurface(hidden);
    key(SDLK_h); auto full=render(); assert(full && full->h>150 && full->h<250); SDL_FreeSurface(full);
    key(SDLK_m);
    std::ifstream opened(std::string(argv[1])+"/menu.toggle"); std::string state; std::getline(opened,state);
    assert(state=="open");
    key(SDLK_m,KMOD_RCTRL|KMOD_RALT|KMOD_RSHIFT);
    std::ifstream closed(std::string(argv[1])+"/menu.toggle"); std::getline(closed,state); assert(state=="closed");
    SDL_Event altTab{}; altTab.type=SDL_KEYDOWN; altTab.key.keysym.sym=SDLK_TAB; altTab.key.keysym.mod=KMOD_ALT;
    SDL_PushEvent(&altTab); SDL_Event received{}; assert(SDL_PollEvent(&received));
    assert(received.type==SDL_KEYDOWN && received.key.keysym.sym==SDLK_TAB);
    TTF_CloseFont(font); TTF_Quit(); SDL_Quit();
}
''')
            flags=subprocess.check_output(['pkg-config','--cflags','--libs','sdl2','SDL2_ttf'],text=True).split()
            if subprocess.run(['pkg-config','--exists','glesv2']).returncode == 0:
                flags += subprocess.check_output(['pkg-config','--cflags','--libs','glesv2'],text=True).split()
                flags += ['-DVASTGAME_GLES_MENU']
            library=root/'hud.so'; executable=root/'test'
            subprocess.run(['g++','-std=c++17','-shared','-fPIC',str(ROOT/'src/client/moonlight_hud.cpp'),
                            str(ROOT/'src/client/stream_menu.cpp'),'-o',str(library),*flags,'-ldl','-pthread'],check=True)
            subprocess.run(['g++','-std=c++17',str(harness),'-o',str(executable),*flags],check=True)
            env=dict(os.environ,SDL_VIDEODRIVER='dummy',LD_PRELOAD=str(library),VASTGAME_HUD_DIR=str(root),
                     VASTGAME_HUD_FONT='/usr/share/fonts/TTF/DejaVuSans.ttf')
            subprocess.run([str(executable),str(root)],env=env,check=True)
            self.assertEqual((root/'moonlight.txt').read_text(),STATS)


if __name__=='__main__': unittest.main()
