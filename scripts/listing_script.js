
		function numberWithCommas(x) {
			if (x !== null) {
				return x.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
			}
		}

		$(function() {

			var locality = {};
			locality['Gurugram'] = ['DLF City Phase II', 'DLF City Phase IV', 'DLF City Phase I,II and III', 'Sector 91/ 92', 'Alameda, Sector 73', 'Sector 81', 'Sector 86', 'Sector 90', 'Sector 54', 'Sector 42', 'DLF City phase I and III'];
			locality['Lucknow'] = ['Vibhuti Khand, Gomti Nagar'];
			locality['Chandigarh'] = ['Mullanpur'];
			locality['Panchkula'] = ['Panchkula', 'Sector 3'];
			locality['Kochi'] = ['Vytilla', 'Kakkanad'];
			locality['Chennai'] = ['Siruseri'];
			locality['Delhi'] = ['Greater Kailash-2', 'Delhi'];

			$('select[name="city"]').on('change', function() {
				var model = $('#locality');
				var educ = $('select[name="city"]').val();
				$('#locality').find('option').remove()

				$('#locality').append('<option value="">Select</option>')

				var ed = locality[educ];
				if (ed) {
					var i;
					for (i = 0; i < ed.length; i++) {
						//var e = new Option(ed[i], ed[i]);
						$('#locality').append('<option value="' + ed[i] + '">' + ed[i] + '</option>')

					}
				}
				$('select').niceSelect('update'); // add this

			});

			var project_type = {};
			project_type['DLF City Phase II'] = ['Low Rise Floors'];
			project_type['DLF City Phase IV'] = ['Low Rise Floors'];
			project_type['DLF City Phase I,II and III'] = ['Low Rise Floors'];
			project_type['Sector 91/ 92'] = ['Low Rise Floors'];
			project_type['Alameda, Sector 73'] = ['Low Rise Floors'];
			project_type['Siruseri'] = ['Plots'];
			project_type['Delhi'] = ['High Rise Apartments'];
			project_type['Sector 81'] = ['High Rise Apartments'];
			project_type['Sector 86'] = ['High Rise Apartments'];
			project_type['Sector 90'] = ['High Rise Apartments'];
			project_type['Vibhuti Khand, Gomti Nagar'] = ['Shops and offices'];
			project_type['Panchkula'] = ['Low Rise Floors'];
			project_type['Sector 42'] = ['High Rise Apartments'];
			project_type['Mullanpur'] = ['Plots'];
			project_type['Greater Kailash-2'] = ['High Rise Apartments'];
			project_type['Sector 54'] = ['NA'];
			project_type['Moti Nagar'] = ['High Rise Apartments'];
			project_type['Kakkanad'] = ['High Rise Apartments'];
			project_type['Vytilla'] = ['High Rise Apartments'];
			project_type['Egmore'] = ['High Rise Apartments'];
			project_type['DLF City phase I and III'] = ['Low Rise Floors'];


			$('select[name="locality"]').on('change', function() {
				var model = $('#project_type');
				var educ = $('select[name="locality"]').val();
				$('#project_type').find('option').remove()

				$('#project_type').append('<option value="">Select</option>')
				var ed = project_type[educ];
				if (ed) {
					var i;
					for (i = 0; i < ed.length; i++) {
						//var e = new Option(ed[i], ed[i]);
						$('#project_type').append('<option value="' + ed[i] + '">' + ed[i] + '</option>')

					}
				}
				$('select').niceSelect('update'); // add this

			});

			load_projects('construction', 'load');

			$(document).on('click', '.filter_search', function() {
				var $type = $(this).data('type')

				if (typeof $type !== "undefined") {
					load_projects($type);
					return;
				}
				$('.tab_list li').removeClass('active');
				$('.tab_list li:first-child').addClass('active');
				var category = '';
				load_projects('construction')
			});

			$(document).on('click', '.display_box', function() {
				$(this).next('.display_box_content').slideToggle();
			});

			function load_projects(type = 'construction', load_type = 'search') {
				var data = $('#searchbox-listing').serialize();
				var category = '';

				if (category == 'super-luxury' && load_type == 'load') {
					type = 'construction';
				}

				$.ajax({
					url: "https://www.dlf.in/load-projects.php",
					method: "POST",
					data: data + '&status=' + type + '&category=' + category,
					success: function(response) {
						$(".listings-show").html(response);
						if (category == 'super-luxury' && load_type == 'load') {
							$('.tab_list li').removeClass('active');
							$('.tab_list li:eq(0)').addClass('active');
						}
					}
				});
			}

			//slider range init set
			$("#slider-range").slider({
				range: true,
				min: 100,
				max: 1000,
				values: [100, 1000],
				slide: function(event, ui) {
					$("#min").html(numberWithCommas(ui.values[0]));
					$("#max").html(numberWithCommas(ui.values[1]));
				}
			});

			//slider range data tooltip set
			var $handler = $("#slider-range .ui-slider-handle");

			$handler.eq(0).append("<b class='amount'><span id='min'>" + numberWithCommas($("#slider-range").slider("values", 0)) + "</span></b>");
			$handler.eq(1).append("<b class='amount'><span id='max'>" + numberWithCommas($("#slider-range").slider("values", 1)) + "</span></b>");

			//slider range pointer mousedown event
			$handler.on("mousedown", function(e) {
				e.preventDefault();
				$(this).children(".amount").fadeIn(300);
			});

			//slider range pointer mouseup event
			$handler.on("mouseup", function(e) {
				e.preventDefault();
				$(this).children(".amount").fadeOut(300);
			});
		});
	