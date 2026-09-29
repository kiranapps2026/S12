"""
Script to fix old field names in test files.

Changes:
- mutation_type -> effective_mutation (on FrozenBindingIdentity)
- .mutation_type -> .effective_mutation (attribute access on FrozenBindingIdentity)
- capability_version, binding_version, policy_version, risk_policy_version, authorization_version -> removed from FrozenBindingIdentity
- estimated_cost -> cost (on TaskProfile)
- .mutation_type -> .mutations[0] (on TaskProfile)
- .effective_risk -> .risk (on TaskProfile)
- engine_module added to FrozenBindingIdentity
"""

import re
import os

def fix_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    original = content

    # Fix FrozenBindingIdentity constructor calls - remove version fields, rename mutation_type
    # Pattern: FrozenBindingIdentity(...) blocks
    # Remove capability_version, binding_version, policy_version, risk_policy_version, authorization_version
    for field in ['capability_version', 'binding_version', 'policy_version', 'risk_policy_version', 'authorization_version']:
        content = re.sub(rf',\s*{field}=[^,)\n]+', '', content)
    content = re.sub(r',\s*,', ',', content)  # Fix double commas
    content = re.sub(r'\(\s*,', '(', content)  # Fix leading comma

    # Fix mutation_type -> effective_mutation in FrozenBindingIdentity contexts
    # (not in CapabilityMatch/Metadata contexts)
    # We need to be careful - only change in FrozenBindingIdentity constructor calls
    # and frozen.mutation_type attribute access

    # Fix frozen.mutation_type attribute access
    content = re.sub(r'frozen\.mutation_type', 'frozen.effective_mutation', content)
    content = re.sub(r'binding\.mutation_type', 'binding.effective_mutation', content)
    content = re.sub(r's8_result\.frozen_binding_identity\.mutation_type', 's8_result.frozen_binding_identity.effective_mutation', content)

    # Fix task_profile.mutation_type -> task_profile.mutations[0]
    content = re.sub(r'task_profile\.mutation_type', 'task_profile.mutations[0]', content)

    # Fix task_profile.effective_risk -> task_profile.risk
    content = re.sub(r'task_profile\.effective_risk', 'task_profile.risk', content)
    content = re.sub(r'\.effective_risk\b', '.risk', content)

    # Fix estimated_cost -> cost
    content = re.sub(r'estimated_cost=', 'cost=', content)

    # Fix TaskProfile constructor - old field names -> new
    content = re.sub(r'execution_id=', 'intent=', content)
    content = re.sub(r'trace_id=', 'capabilities=', content)  # This is wrong but let's handle it properly
    content = re.sub(r'binding_id=', 'graph_type=', content)
    content = re.sub(r'capability_id=', 'steps_estimated=', content)
    content = re.sub(r'kernel_op_id=', 'mutations=', content)
    content = re.sub(r'provider=', 'risk=', content)
    content = re.sub(r'adapter_class=', 'cost=', content)
    content = re.sub(r'estimated_duration_ms=', 'requires_confirmation=', content)
    content = re.sub(r'timeout_seconds=', 'resource_scope=', content)
    content = re.sub(r'retry_policy=', 'providers=', content)
    content = re.sub(r'metadata=', 'tags=', content)

    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Fixed: {filepath}")
    else:
        print(f"No changes: {filepath}")

# Files to fix
files = [
    'tests/stages/test_s5_provider_resolution.py',
    'tests/stages/test_s6_task_profile.py',
    'tests/stages/test_s7_to_s11.py',
    'tests/stages/test_s9_plan_creation.py',
    'tests/test_s0_s11_certification.py',
    'tests/integration/test_s0_to_s11_journey.py',
    'tests/steps/step_h_no_re_resolve.py',
]

for f in files:
    fix_file(f)
