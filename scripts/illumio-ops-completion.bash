# illumio-ops bash completion
# Install by sourcing in ~/.bashrc or dropping in /etc/bash_completion.d/
#
# Regenerate with: _ILLUMIO_OPS_COMPLETE=bash_source illumio-ops > illumio-ops-completion.bash

_illumio_ops_completion() {
    local IFS=$'\n'
    local response

    response=$(env COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD=$COMP_CWORD \
        _ILLUMIO_OPS_COMPLETE=bash_complete illumio-ops)

    for completion in $response; do
        IFS=',' read type value <<< "$completion"

        if [[ $type == 'dir' ]]; then
            COMPREPLY=()
            compopt -o dirnames
        elif [[ $type == 'file' ]]; then
            COMPREPLY=()
            compopt -o default
        elif [[ $type == 'plain' ]]; then
            COMPREPLY+=($value)
        fi
    done

    return 0
}

_illumio_ops_completion_setup() {
    complete -o nosort -F _illumio_ops_completion illumio-ops
}

_illumio_ops_completion_setup
