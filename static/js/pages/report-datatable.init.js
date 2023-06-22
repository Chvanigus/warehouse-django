$(document).ready(function () {
    const scriptElement = document.getElementById('json_url')
    $('#report-datatable').DataTable({
        language: {
            url: scriptElement.getAttribute('data-json-url'),
        },
        dom: 'Bfrtip',
        buttons: [
            'copy', 'excel',
        ],
        paging: true,
        ordering: true,
        rowGroup: {
            dataSrc: 0
        },
        columnDefs: [
            {
                targets: 0,
                visible: false
            }
        ],
        order: [[1, 'asc']]
    });
});