const languageUrl = document.currentScript.dataset.languageUrl;

for (const table of document.querySelectorAll('.report-datatable')) {
    const exportOptions = {columns: ':not(.no-export)', escapeExcelFormula: true};

    new DataTable(table, {
        language: {url: languageUrl},
        layout: {
            topStart: {
                buttons: [
                    {extend: 'copyHtml5', text: 'Копировать', exportOptions},
                    {extend: 'excelHtml5', text: 'Excel', title: table.dataset.exportTitle || document.title, exportOptions},
                ],
            },
        },
        order: [],
        columnDefs: [{targets: 'th.no-export', orderable: false, searchable: false}],
    });
}
