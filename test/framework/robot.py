# #
# Copyright 2012-2014 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
# #
"""
Unit tests for robot (dependency resolution).

@author: Toon Willems (Ghent University)
"""

import os
from copy import deepcopy
from test.framework.utilities import EnhancedTestCase, init_config
from unittest import TestLoader
from unittest import main as unittestmain

import easybuild.framework.easyconfig.tools as ectools
import easybuild.tools.robot as robot
from easybuild.framework.easyconfig.tools import skip_available
from easybuild.tools import config, modules
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.robot import resolve_dependencies
from test.framework.utilities import find_full_path

ORIG_MODULES_TOOL = modules.modules_tool
ORIG_ECTOOLS_MODULES_TOOL = ectools.modules_tool
ORIG_ROBOT_MODULES_TOOL = robot.modules_tool
ORIG_MODULE_FUNCTION = os.environ.get('module', None)


class MockModule(modules.ModulesTool):
    """ MockModule class, allows for controlling what modules_tool() will return """
    COMMAND = 'echo'
    VERSION_OPTION = '1.0'
    VERSION_REGEXP = r'(?P<version>\d\S*)'
    # redirect to stderr, ignore 'echo python' ($0 and $1)
    COMMAND_SHELL = ["bash", "-c", "echo $2 $3 $4 1>&2"]

    avail_modules = []

    def available(self, *args):
        """Dummy implementation of available."""
        return self.avail_modules

    def show(self, modname):
        """Dummy implementation of show, which includes full path to (available or hidden) module files."""
        if modname in self.avail_modules or os.path.basename(modname).startswith('.'):
            txt =  '  %s:' % os.path.join('/tmp', modname)
        else:
            txt = 'Module %s not found' % modname
        return txt

def mock_module(mod_paths=None):
    """Get mock module instance."""
    return MockModule(mod_paths=mod_paths)


class RobotTest(EnhancedTestCase):
    """ Testcase for the robot dependency resolution """

    def setUp(self):
        """Set up everything for a unit test."""
        super(RobotTest, self).setUp()

        # replace Modules class with something we have control over
        config.modules_tool = mock_module
        ectools.modules_tool = mock_module
        robot.modules_tool = mock_module
        os.environ['module'] = "() {  eval `/bin/echo $*`\n}"

        self.base_easyconfig_dir = find_full_path(os.path.join("test", "framework", "easyconfigs"))
        self.assertTrue(self.base_easyconfig_dir)

    def test_resolve_dependencies(self):
        """ Test with some basic testcases (also check if he can find dependencies inside the given directory """
        easyconfig = {
            'spec': '_',
            'full_mod_name': 'name/version',
            'short_mod_name': 'name/version',
            'dependencies': []
        }
        build_options = {
            'allow_modules_tool_mismatch': True,
            'robot_path': None,
            'validate': False,
        }
        init_config(build_options=build_options)
        res = resolve_dependencies([deepcopy(easyconfig)])
        self.assertEqual([easyconfig], res)

        easyconfig_dep = {
            'ec': {
                'name': 'foo',
                'version': '1.2.3',
                'versionsuffix': '',
                'toolchain': {'name': 'dummy', 'version': 'dummy'},
            },
            'spec': '_',
            'short_mod_name': 'foo/1.2.3',
            'full_mod_name': 'foo/1.2.3',
            'dependencies': [{
                'name': 'gzip',
                'version': '1.4',
                'versionsuffix': '',
                'toolchain': {'name': 'dummy', 'version': 'dummy'},
                'dummy': True,
                'hidden': False,
            }],
            'parsed': True,
        }
        build_options.update({'robot': True, 'robot_path': self.base_easyconfig_dir})
        init_config(build_options=build_options)
        res = resolve_dependencies([deepcopy(easyconfig_dep)])
        # dependency should be found, order should be correct
        self.assertEqual(len(res), 2)
        self.assertEqual('gzip/1.4', res[0]['full_mod_name'])
        self.assertEqual('foo/1.2.3', res[-1]['full_mod_name'])

        # hidden dependencies are found too, but only retained if they're not available (or forced to be retained
        hidden_dep = {
            'name': 'toy',
            'version': '0.0',
            'versionsuffix': '-deps',
            'toolchain': {'name': 'dummy', 'version': 'dummy'},
            'dummy': True,
            'hidden': True,
        }
        easyconfig_moredeps = deepcopy(easyconfig_dep)
        easyconfig_moredeps['dependencies'].append(hidden_dep)
        easyconfig_moredeps['hiddendependencies'] = [hidden_dep]

        # toy/.0.0-deps is available and thus should be omitted
        res = resolve_dependencies([deepcopy(easyconfig_moredeps)])
        self.assertEqual(len(res), 2)
        full_mod_names = [ec['full_mod_name'] for ec in res]
        self.assertFalse('toy/.0.0-deps' in full_mod_names)

        res = resolve_dependencies([deepcopy(easyconfig_moredeps)], retain_all_deps=True)
        self.assertEqual(len(res), 4)  # hidden dep toy/.0.0-deps (+1) depends on (fake) ictce/4.1.13 (+1)
        self.assertEqual('gzip/1.4', res[0]['full_mod_name'])
        self.assertEqual('foo/1.2.3', res[-1]['full_mod_name'])
        full_mod_names = [ec['full_mod_name'] for ec in res]
        self.assertTrue('toy/.0.0-deps' in full_mod_names)
        self.assertTrue('ictce/4.1.13' in full_mod_names)

        # here we have included a dependency in the easyconfig list
        easyconfig['full_mod_name'] = 'gzip/1.4'

        ecs = [deepcopy(easyconfig_dep), deepcopy(easyconfig)]
        build_options.update({'robot_path': None})
        init_config(build_options=build_options)
        res = resolve_dependencies(ecs)
        # all dependencies should be resolved
        self.assertEqual(0, sum(len(ec['dependencies']) for ec in res))

        # this should not resolve (cannot find gzip-1.4.eb), both with and without robot enabled
        ecs = [deepcopy(easyconfig_dep)]
        msg = "Irresolvable dependencies encountered"
        self.assertErrorRegex(EasyBuildError, msg, resolve_dependencies, ecs)

        # test if dependencies of an automatically found file are also loaded
        easyconfig_dep['dependencies'] = [{
            'name': 'gzip',
            'version': '1.4',
            'versionsuffix': '',
            'toolchain': {'name': 'GCC', 'version': '4.6.3'},
            'dummy': True,
            'hidden': False,
        }]
        ecs = [deepcopy(easyconfig_dep)]
        build_options.update({'robot_path': self.base_easyconfig_dir})
        init_config(build_options=build_options)
        res = resolve_dependencies([deepcopy(easyconfig_dep)])

        # GCC should be first (required by gzip dependency)
        self.assertEqual('GCC/4.6.3', res[0]['full_mod_name'])
        self.assertEqual('foo/1.2.3', res[-1]['full_mod_name'])

        # make sure that only missing stuff is built, and that available modules are not rebuilt
        # monkey patch MockModule to pretend that all ingredients required for goolf-1.4.10 toolchain are present
        MockModule.avail_modules = [
            'GCC/4.7.2',
            'OpenMPI/1.6.4-GCC-4.7.2',
            'OpenBLAS/0.2.6-gompi-1.4.10-LAPACK-3.4.2',
            'FFTW/3.3.3-gompi-1.4.10',
            'ScaLAPACK/2.0.2-gompi-1.4.10-OpenBLAS-0.2.6-LAPACK-3.4.2',
        ]

        easyconfig_dep['dependencies'] = [{
            'name': 'goolf',
            'version': '1.4.10',
            'versionsuffix': '',
            'toolchain': {'name': 'dummy', 'version': 'dummy'},
            'dummy': True,
            'hidden': False,
        }]
        ecs = [deepcopy(easyconfig_dep)]
        res = resolve_dependencies(ecs)

        # there should only be two retained builds, i.e. the software itself and the goolf toolchain as dep
        self.assertEqual(len(res), 2)
        # goolf should be first, the software itself second
        self.assertEqual('goolf/1.4.10', res[0]['full_mod_name'])
        self.assertEqual('foo/1.2.3', res[1]['full_mod_name'])

        # force doesn't trigger rebuild of all deps, but listed easyconfigs for which a module is available are rebuilt
        build_options.update({'force': True})
        init_config(build_options=build_options)
        easyconfig['full_mod_name'] = 'this/is/already/there'
        MockModule.avail_modules.append('this/is/already/there')
        ecs = [deepcopy(easyconfig_dep), deepcopy(easyconfig)]
        res = resolve_dependencies(ecs)

        # there should only be three retained builds, foo + goolf dep and the additional build (even though a module is available)
        self.assertEqual(len(res), 3)
        # goolf should be first, the software itself second
        self.assertEqual('this/is/already/there', res[0]['full_mod_name'])
        self.assertEqual('goolf/1.4.10', res[1]['full_mod_name'])
        self.assertEqual('foo/1.2.3', res[2]['full_mod_name'])

        # build that are listed but already have a module available are not retained without force
        build_options.update({'force': False})
        init_config(build_options=build_options)
        newecs = skip_available(ecs)  # skip available builds since force is not enabled
        res = resolve_dependencies(newecs)
        self.assertEqual(len(res), 2)
        self.assertEqual('goolf/1.4.10', res[0]['full_mod_name'])
        self.assertEqual('foo/1.2.3', res[1]['full_mod_name'])

        # with retain_all_deps enabled, all dependencies ae retained
        build_options.update({'retain_all_deps': True})
        init_config(build_options=build_options)
        ecs = [deepcopy(easyconfig_dep)]
        newecs = skip_available(ecs)  # skip available builds since force is not enabled
        res = resolve_dependencies(newecs)
        self.assertEqual(len(res), 9)
        self.assertEqual('GCC/4.7.2', res[0]['full_mod_name'])
        self.assertEqual('goolf/1.4.10', res[-2]['full_mod_name'])
        self.assertEqual('foo/1.2.3', res[-1]['full_mod_name'])

        build_options.update({'retain_all_deps': False})
        init_config(build_options=build_options)

        # provide even less goolf ingredients (no OpenBLAS/ScaLAPACK), make sure the numbers add up
        MockModule.avail_modules = [
            'GCC/4.7.2',
            'OpenMPI/1.6.4-GCC-4.7.2',
            'gompi/1.4.10',
            'FFTW/3.3.3-gompi-1.4.10',
        ]

        easyconfig_dep['dependencies'] = [{
            'name': 'goolf',
            'version': '1.4.10',
            'versionsuffix': '',
            'toolchain': {'name': 'dummy', 'version': 'dummy'},
            'dummy': True,
            'hidden': False,
        }]
        ecs = [deepcopy(easyconfig_dep)]
        res = resolve_dependencies([deepcopy(easyconfig_dep)])

        # there should only be two retained builds, i.e. the software itself and the goolf toolchain as dep
        self.assertEqual(len(res), 4)
        # goolf should be first, the software itself second
        self.assertEqual('OpenBLAS/0.2.6-gompi-1.4.10-LAPACK-3.4.2', res[0]['full_mod_name'])
        self.assertEqual('ScaLAPACK/2.0.2-gompi-1.4.10-OpenBLAS-0.2.6-LAPACK-3.4.2', res[1]['full_mod_name'])
        self.assertEqual('goolf/1.4.10', res[2]['full_mod_name'])
        self.assertEqual('foo/1.2.3', res[3]['full_mod_name'])

    def tearDown(self):
        """ reset the Modules back to its original """
        super(RobotTest, self).tearDown()

        config.modules_tool = ORIG_MODULES_TOOL
        ectools.modules_tool = ORIG_ECTOOLS_MODULES_TOOL
        robot.modules_tool = ORIG_ROBOT_MODULES_TOOL
        if ORIG_MODULE_FUNCTION is not None:
            os.environ['module'] = ORIG_MODULE_FUNCTION
        else:
            if 'module' in os.environ:
                del os.environ['module']


def suite():
    """ returns all the testcases in this module """
    return TestLoader().loadTestsFromTestCase(RobotTest)

if __name__ == '__main__':
    unittestmain()
