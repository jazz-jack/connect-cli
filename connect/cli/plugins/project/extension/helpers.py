import collections
import os

import yaml
from click.exceptions import ClickException
from interrogatio.core.dialog import dialogus

from connect.cli.core.terminal import console
from connect.cli.plugins.project.utils import show_validation_result_table
from connect.cli.plugins.project.renderer import BoilerplateRenderer
from connect.cli.plugins.project.extension.utils import get_event_definitions, get_pypi_runner_version
from connect.cli.plugins.project.extension.validations import validators
from connect.cli.plugins.project.extension.wizard import (
    EXTENSION_BOOTSTRAP_WIZARD_INTRO,
    get_questions,
    get_summary,
)


def bootstrap_extension_project(config, output_dir, overwrite):  # noqa: CCR001
    console.secho('Bootstraping extension project...\n', fg='blue')

    statuses_by_event = collections.defaultdict(lambda: collections.defaultdict())

    definitions = get_event_definitions(config)
    grouped_definitions = collections.defaultdict(lambda: collections.defaultdict(list))

    for elem in definitions:
        statuses_by_event[elem['extension_type']][elem['type']] = elem['object_statuses']
        grouped_definitions[elem['extension_type']][elem['category']].append(elem)

    answers = dialogus(
        get_questions(config, grouped_definitions),
        'Extension project bootstrap',
        intro=EXTENSION_BOOTSTRAP_WIZARD_INTRO,
        summary=get_summary,
        finish_text='Create',
        previous_text='Back',
    )

    if not answers:
        raise ClickException('Aborted by user input')

    ctx = {
        'statuses_by_event': statuses_by_event[answers['extension_type']],
        'interactive': [],
        'runner_version': get_pypi_runner_version(),
    }

    for var, answer in answers.items():
        ctx.update({var: answer})

    project_dir = os.path.join(output_dir, ctx['project_slug'])
    if not overwrite and os.path.exists(project_dir):
        raise ClickException(f'The destination directory {project_dir} already exists.')

    exclude = []

    if answers['use_github_actions'] == 'n':
        exclude = [
            os.path.join(
                answers['project_slug'],
                '.github',
            ),
            os.path.join(
                answers['project_slug'],
                '.github',
                'workflows',
            ),
            os.path.join(
                answers['project_slug'],
                '.github',
                'workflows',
                'build.yml.j2',
            ),
        ]

    if 'webapp' not in answers.get('application_types', []):
        exclude.append(
            os.path.join(
                answers['project_slug'],
                answers['package_name'],
                'static_root',
            ),
        )

        exclude.extend([
            os.path.join(
                answers['project_slug'],
                answers['package_name'],
                'static_root',
                static_file,
            ) for static_file in [
                'index.html.j2',
                'page1.html.j2',
                'settings.html.j2',
            ]
        ])

    application_types = answers.get('application_types', [])
    if answers['extension_type'] != 'multiaccount':
        application_types.append('events')

    for app_type in ['anvil', 'events', 'webapp']:
        if app_type not in application_types:
            exclude.append(
                os.path.join(
                    answers['project_slug'],
                    answers['package_name'],
                    f'{app_type}.py.j2',
                ),
            )
            exclude.append(
                os.path.join(
                    answers['project_slug'],
                    'tests',
                    f'test_{app_type}.py.j2',
                ),
            )

    renderer = BoilerplateRenderer(
        context=ctx,
        template_folder=os.path.join(
            os.path.dirname(__file__),
            'templates',
            'bootstrap',
        ),
        output_dir=output_dir,
        overwrite=overwrite,
        exclude=exclude,
    )
    renderer.render()

    console.markdown(open(f'{project_dir}/HOWTO.md', 'r').read())


def validate_extension_project(config, project_dir):  # noqa: CCR001
    console.secho(f'Validating project {project_dir}...\n', fg='blue')

    context = {}

    validation_items = []

    for validator in validators:
        result = validator(config, project_dir, context)
        validation_items.extend(result.items)
        if result.must_exit:
            break
        if result.context:
            context.update(result.context)

    if validation_items:
        console.markdown('# Extension validation results')
        show_validation_result_table(validation_items)
        console.secho(
            f'Warning/errors have been found while validating the Extension Project {project_dir}.',
            fg='yellow',
        )
    else:
        console.secho(f'Extension Project {project_dir} has been successfully validated.', fg='green')


def bump_runner_extension_project(project_dir: str):
    console.secho(f'Bumping runner version on project {project_dir}...\n', fg='blue')

    latest_version = get_pypi_runner_version()
    docker_compose_file = os.path.join(project_dir, 'docker-compose.yml')
    if not os.path.isfile(docker_compose_file):
        raise ClickException(f'Mandatory `docker-compose.yml` file on directory `{project_dir}` is missing.')
    try:
        with open(docker_compose_file, 'r') as file_reader:
            data = yaml.load(file_reader, Loader=yaml.FullLoader)
            for service in data['services']:
                if 'image' in data['services'][service]:
                    runner_image = data['services'][service]['image']
                    runner_version = runner_image.split(':')[-1]
                    updated_image = runner_image.replace(runner_version, latest_version)
                    data['services'][service]['image'] = updated_image
        with open(docker_compose_file, 'w') as file_writer:
            yaml.dump(data, file_writer, sort_keys=False)
    except yaml.YAMLError as error:
        raise ClickException(
            '`docker_compose.yml` file is not properly formatted. Please review it.\n'
            f'Error: {error}',
        )

    console.secho(f'Runner version has been successfully updated to {latest_version}', fg='green')
