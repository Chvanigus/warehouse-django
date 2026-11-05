const languageUrl = document.currentScript.dataset.languageUrl;

for (const table of document.querySelectorAll('.report-datatable')) {
    const stockWorkspace = table.hasAttribute('data-stock-workspace');
    const exportOptions = {columns: ':not(.no-export)', escapeExcelFormula: true};

    new DataTable(table, {
        language: {url: languageUrl},
        layout: {
            topStart: {
                buttons: [
                    {extend: 'copyHtml5', text: 'Копировать', exportOptions},
                    {
                        extend: 'excelHtml5',
                        text: stockWorkspace ? 'Скачать XLSX' : 'Excel',
                        title: table.dataset.exportTitle || document.title,
                        exportOptions,
                    },
                ],
            },
            ...(stockWorkspace ? {topEnd: null} : {}),
        },
        searching: !stockWorkspace,
        order: [],
        columnDefs: [
            {targets: 'th.no-export:not(.stock-sortable)', orderable: false, searchable: false},
            {targets: 'th[data-export-only]', visible: false},
        ],
    });
}
