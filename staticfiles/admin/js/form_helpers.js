
window.addEventListener("load", function() {

    document.body.addEventListener('change', function(event) {
        if (event.target.name && event.target.name.endsWith('-origin_question')) {
            const questionId = event.target.value;
            const row = event.target.closest('tr');

            if (!questionId) {
                clearSnapshotFields(row);
                return;
            }

            if (!row) {
                console.error("Could not find the parent row (tr) for the changed element.");
                return;
            }

            fetch(`/api/question-details/${questionId}/`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.error) {
                        console.error('API Error:', data.error);
                        return;
                    }
                    populateSnapshotFields(row, data);
                })
                .catch(err => console.error('Fetch Error:', err));
        }
    });

    document.addEventListener('djnesting:added', function(event) {
        const newRow = event.detail.row;
        if (!newRow) return;

        const formTopicGroup = newRow.closest('.djn-inline-form');
        if (!formTopicGroup) return;

        const topicSelect = formTopicGroup.querySelector('select[name$="-topic"]');
        if (!topicSelect || topicSelect.value === '') return;

        const topicName = topicSelect.options[topicSelect.selectedIndex].text;

        const topicSnapshotInput = newRow.querySelector('[name$="-topic_snapshot"]');
        if (topicSnapshotInput) {
            topicSnapshotInput.value = topicName;
        }
    });

    function populateSnapshotFields(row, data) {
        const fields = {
            'text_snapshot': data.text_snapshot,
            'difficulty_snapshot': data.difficulty_snapshot,
            'source_snapshot': data.source_snapshot,
            'max_score_snapshot': data.max_score_snapshot
        };

        for (const fieldName in fields) {
            const input = row.querySelector(`[name$="-${fieldName}"]`);
            if (input) input.value = fields[fieldName] || '';
        }
    }

    function clearSnapshotFields(row) {
        if (!row) return;
        const fieldNames = ['text_snapshot', 'difficulty_snapshot', 'source_snapshot', 'topic_snapshot', 'max_score_snapshot'];
        fieldNames.forEach(fieldName => {
            const input = row.querySelector(`[name$="-${fieldName}"]`);
            if (input) input.value = '';
        });
    }
});
