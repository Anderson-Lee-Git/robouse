"""Prompt protocol tests; builders and scripted stand-ins only, no model calls."""
import hashlib
import json
from pathlib import Path

import pytest

from robouse import harnesses as H
from robouse.cli import main, parser
from robouse.harnesses import interface as I
from robouse.harnesses import program
from robouse.runner.atif import _prompt
from robouse.tasks import Task

ORIGINAL = (
    "You are controlling a simulated robot. Read the task below, then solve it by running the `robo` command "
    "in your shell (start with `robo info` and `robo observe`). Keep going until the task is done, then call "
    "`robo done` once. Do not stop to ask questions; there is no human to answer.\n\n"
)


def test_default_prefix_is_byte_identical():
    assert H.PROMPT_PREFIX.encode() == ORIGINAL.encode()
    assert H.frame_prompt(ORIGINAL).encode() == ORIGINAL.encode()


@pytest.mark.parametrize('harness', ['claude-code', 'codex'])
@pytest.mark.parametrize('interface', I.INTERFACES)
def test_direct_build_and_interfaces_change_only_opening_phrase(tmp_path, monkeypatch, harness, interface):
    # Stub credential setup, while keeping the real command builders and interface adapter.
    monkeypatch.setattr(H, '_via_gateway', lambda *a: None)
    monkeypatch.setattr(H.credentials, 'claude_auth', lambda: {})
    monkeypatch.setattr(H.credentials, 'clean_claude_home', lambda ws: str(ws))
    monkeypatch.setattr(H.credentials, 'clean_codex_home', lambda **kw: str(tmp_path))
    monkeypatch.setattr(H.credentials, 'remove_trial_home', lambda *a: None)
    ws = tmp_path
    (ws / '.robouse/bin').mkdir(parents=True)
    prompts = []
    for framing in ('simulated', 'real'):
        launch = H.build(harness, '', 'TASK', ws, None, {H.ROBOT_FRAMING_ENV: framing})
        I.apply(harness, launch, interface, ws, '/tmp/test.sock')
        prompts.append(next(a for a in launch.cmd if a.startswith('You are controlling')))
        assert H.ROBOT_FRAMING_ENV not in launch.env
    assert prompts[0] == I.prompt_prefix(interface) + 'TASK'
    assert prompts[1] == prompts[0].replace('You are controlling a simulated robot.', 'You are controlling a real robot.', 1)


@pytest.mark.parametrize('harness', ['program', 'program-codex'])
def test_program_persisted_inner_prompt_changes_only_phrase(tmp_path, monkeypatch, harness):
    def stub(agent, model, prompt, ws, task, env):
        assert H.ROBOT_FRAMING_ENV not in env
        return H.Launch(['agent', prompt], env)
    monkeypatch.setattr(program, 'agent_launch', stub)
    monkeypatch.setattr(program.ProgramBroker, 'start', lambda self: 'http://127.0.0.1:1')
    prompts = []
    for framing in ('simulated', 'real'):
        ws = tmp_path / framing
        ws.mkdir()
        task = Task(tmp_path / 'task', {'robouse': {}}, 'TASK')
        env = {H.ROBOT_FRAMING_ENV: framing, '_ROBOUSE_TRIAL_DIR': str(tmp_path / ('trial-' + framing))}
        launch = H.build(harness, '', 'TASK', ws, task, env)
        try:
            text = launch.config['prompt']
            prompts.append(text)
            template = (program.HERE / 'workspace/PROGRAM.md').read_text().replace('{{max_runs}}', '40').replace('{{max_steps}}', '0')
            assert (ws / 'PROGRAM.md').read_text() == program.frame_program_doc(template, framing)
            driver = json.loads((ws / '.robouse/program/driver.json').read_text())
            assert driver['agent_cmd'] == ['agent', text]
            assert 'a fresh reset of the scene' in text
            assert H.ROBOT_FRAMING_ENV not in launch.env
            assert _prompt(tmp_path, {'harness_config': launch.config, 'robot_framing': framing}, harness) == text
        finally:
            launch.stop()
    assert prompts[1] == prompts[0].replace('a program that controls a simulated robot.', 'a program that controls a real robot.', 1)


@pytest.mark.parametrize('base', H.ROBOT_FRAMING_HARNESSES)
def test_plugins_use_base_contract(tmp_path, monkeypatch, base):
    def plugin(harness, model, prompt, ws, task, env):
        if base.startswith('program'):
            text = H.frame_prompt('You are writing a program that controls a simulated robot.', env[H.ROBOT_FRAMING_ENV], program=True)
            return H.Launch(['driver'], env, config={'prompt': text})
        return H.Launch(['agent', H.PROMPT_PREFIX + prompt], env, config={'prompt': H.PROMPT_PREFIX + prompt})
    plugin.robouse_base = base
    monkeypatch.setattr(H, 'plugin', lambda _: plugin)
    assert H.robot_framing_refusal('plugin', 'real') is None
    launch = H.build('plugin', '', 'TASK', tmp_path, None, {H.ROBOT_FRAMING_ENV: 'real'})
    assert H.ROBOT_FRAMING_ENV not in launch.env
    assert 'real robot.' in (launch.config.get('prompt') or launch.cmd[-1])


@pytest.mark.parametrize('harness', [h for h in H.HARNESSES if h not in H.ROBOT_FRAMING_HARNESSES])
def test_other_harnesses_refuse_before_build(tmp_path, harness):
    assert H.robot_framing_refusal(harness) is None
    assert 'not ' + harness in H.robot_framing_refusal(harness, 'real')
    with pytest.raises(ValueError, match='--robot-framing real applies'):
        H.build(harness, '', 'TASK', tmp_path, None, {H.ROBOT_FRAMING_ENV: 'real'})


def test_missing_phrase_raises(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='expected prompt phrase'):
        H.frame_prompt('changed prefix', 'real')
    with pytest.raises(ValueError, match='expected prompt phrase'):
        H.frame_prompt('changed program preamble', 'real', program=True)
    monkeypatch.setitem(H.HARNESSES, 'claude-code', lambda *a: H.Launch(['agent', 'changed prefix'], {}))
    with pytest.raises(RuntimeError, match='expected simulated robot prompt phrase'):
        H.build('claude-code', '', 'TASK', tmp_path, None, {H.ROBOT_FRAMING_ENV: 'real'})


@pytest.mark.parametrize('cmd', ['run', 'run-many'])
def test_cli_records_choice_and_refuses_unsupported(cmd, capsys):
    args = [cmd, '--task' if cmd == 'run' else '--tasks', 'unused', '--out', 'unused', '--harness', 'noop']
    assert parser().parse_args(args).robot_framing == 'simulated'
    assert main(args + ['--robot-framing', 'real']) == 2
    assert '--robot-framing real applies' in capsys.readouterr().err


def test_atif_reconstructs_framing_and_extra_instruction(tmp_path, monkeypatch):
    from robouse import tasks
    monkeypatch.setattr(tasks, 'load_task', lambda _: Task(tmp_path, {}, 'TASK'))
    cfg = {'task_path': 'unused', 'interface': 'both', 'robot_framing': 'real', 'extra_instruction': 'Plan ahead.'}
    assert _prompt(tmp_path, cfg, 'codex') == I.prompt_prefix('both', 'real') + 'TASK\n\nPlan ahead.\n'


@pytest.mark.parametrize('framing', ['simulated', 'real'])
def test_trial_config_records_framing_without_agent_or_model(tmp_path, monkeypatch, framing):
    # Stop deliberately at server spawn, after config.json was written. No simulator or agent runs.
    from robouse.runner import trial
    from robouse.tasks import load_task
    task = load_task(Path(__file__).resolve().parents[1] / 'tasks/arc-style/arc-gravity')
    def stop(*args, **kwargs):
        raise OSError('intentional test: server never started')
    monkeypatch.setattr(trial.subprocess, 'Popen', stop)
    with pytest.raises(OSError, match='intentional test'):
        trial.run_trial(task, 'claude-code', '', tmp_path, robot_framing=framing)
    cfg = json.loads(next(tmp_path.glob('*/config.json')).read_text())
    assert cfg['robot_framing'] == framing


def test_resume_cannot_mix_framings(tmp_path):
    from robouse.runner.jobs import resume_refusal
    d = tmp_path / 'trial'
    d.mkdir()
    (d / 'config.json').write_text(json.dumps({'harness': 'claude-code', 'model': ''}))
    assert resume_refusal(tmp_path, 'claude-code', '') is None
    assert 'robot_framing' in resume_refusal(tmp_path, 'claude-code', '', robot_framing='real')


@pytest.mark.parametrize('interface,digest', [
    ('cli', 'ad25e3aecf190d7881afe73f9a59031763a6293faab1a1107247861923ddbea5'),
    ('mcp', '38cbdcfd6559227f62aefd9f0e022007e29b978c76b426cadb416e17ba607e8e'),
    ('both', '3874feb0b81dc9535a3bf290807ff470dfc0504cfe9861d3c7d35f1ebbd9c9db'),
])
def test_default_prompt_bytes_match_pre_framing_snapshot(interface, digest):
    assert hashlib.sha256(I.prompt_prefix(interface).encode()).hexdigest() == digest


def test_run_many_records_and_passes_framing(tmp_path, monkeypatch):
    from robouse.runner import jobs
    seen = []
    monkeypatch.setattr(jobs, 'select_tasks', lambda *a: [Task(tmp_path / 'task', {}, 'TASK')])
    def stub(*args, **kwargs):
        seen.append(kwargs['robot_framing'])
        return {'exception': None, 'reward': 0, 'outcome': 'test', 'steps': 0, 'wall_s': 0}
    monkeypatch.setattr(jobs, 'run_trial', stub)
    jobs.run_many(tmp_path, 'claude-code', '', tmp_path / 'out', robot_framing='real')
    assert seen == ['real']
    assert json.loads((tmp_path / 'out/job.json').read_text())['robot_framing'] == 'real'


@pytest.mark.parametrize('base', ['claude-code', 'codex'])
def test_plugin_delegating_to_build_is_not_double_framed(tmp_path, monkeypatch, base):
    monkeypatch.setattr(H, '_via_gateway', lambda *a: None)
    monkeypatch.setattr(H.credentials, 'claude_auth', lambda: {})
    monkeypatch.setattr(H.credentials, 'clean_claude_home', lambda ws: str(ws))
    monkeypatch.setattr(H.credentials, 'clean_codex_home', lambda **kw: str(tmp_path))
    monkeypatch.setattr(H.credentials, 'remove_trial_home', lambda *a: None)
    def plugin(harness, model, prompt, ws, task, env):
        return H.build(base, model, prompt, ws, task, env)
    plugin.robouse_base = base
    monkeypatch.setattr(H, 'plugin', lambda _: plugin)
    launch = H.build('plugin', '', 'TASK', tmp_path, None, {H.ROBOT_FRAMING_ENV: 'real'})
    assert any(a.startswith('You are controlling a real robot.') for a in launch.cmd)
    assert H.ROBOT_FRAMING_ENV not in launch.env


@pytest.mark.parametrize('framing', ['simulated', 'real'])
def test_program_workspace_document_bytes(tmp_path, framing):
    template = (program.HERE / 'workspace/PROGRAM.md').read_text()
    program.prepare_workspace(tmp_path, {'max_runs': 40, 'max_steps': 900}, framing)
    expected = template.replace('{{max_runs}}', '40').replace('{{max_steps}}', '900')
    if framing == 'real':
        for old, new in program.PROGRAM_FRAMING_EDITS:
            expected = expected.replace(old, new, 1)
        assert 'simulated' not in expected
    assert (tmp_path / 'PROGRAM.md').read_bytes() == expected.encode()
    assert 'a fresh reset of the scene' in expected


@pytest.mark.parametrize('old,new', program.PROGRAM_FRAMING_EDITS)
def test_program_doc_missing_phrase_raises(old, new):
    template = (program.HERE / 'workspace/PROGRAM.md').read_text().replace(old, new)
    with pytest.raises(ValueError, match='expected PROGRAM.md phrase'):
        program.frame_program_doc(template, 'real')
    assert program.frame_program_doc(template) == template
