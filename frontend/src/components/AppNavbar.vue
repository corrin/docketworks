<template>
  <nav
    class="bg-white border-b border-gray-200 px-3 sm:px-6 py-1 md:py-0.5 lg:py-3 xl:py-4 fixed top-0 left-0 right-0 z-50 transition-all duration-200"
  >
    <div class="flex items-center justify-between h-10 md:h-8 lg:h-auto">
      <div class="flex items-center">
        <button
          @click="toggleMobileMenu"
          class="lg:hidden mr-2 p-1 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition-colors duration-200"
        >
          <Menu v-if="!showMobileMenu" class="h-4 w-4" />
          <X v-else class="h-4 w-4" />
        </button>
        <div class="hidden lg:flex items-center space-x-6">
          <router-link
            :to="kanbanNav.to"
            class="flex items-center text-gray-700 hover:text-blue-600 transition-colors text-sm font-medium"
          >
            <Kanban class="w-4 h-4 mr-1" /> {{ kanbanNav.label }}
          </router-link>

          <router-link
            v-if="userInfo.is_office_staff"
            to="/jobs/create"
            class="flex items-center text-gray-700 hover:text-blue-600 transition-colors text-sm font-medium"
            data-automation-id="AppNavbar-create-job"
          >
            <FilePlus class="w-4 h-4 mr-1" /> Create Job
          </router-link>

          <div class="relative group">
            <div v-if="userInfo.is_office_staff">
              <button
                @click="toggleDropdown('timesheets')"
                class="flex items-center space-x-1 px-3 py-2 rounded-md text-sm font-medium text-gray-700 hover:text-blue-600 hover:bg-gray-50 transition-colors duration-200 z-60"
              >
                <Calendar class="w-4 h-4" />
                <span>Timesheets</span>
                <ChevronDown class="w-4 h-4" />
              </button>

              <Transition
                enter-active-class="transition-all duration-300 ease-out"
                enter-from-class="opacity-0 -translate-y-2 scale-95"
                enter-to-class="opacity-100 translate-y-0 scale-100"
                leave-active-class="transition-all duration-200 ease-in"
                leave-from-class="opacity-100 translate-y-0 scale-100"
                leave-to-class="opacity-0 -translate-y-2 scale-95"
              >
                <div
                  v-if="activeDropdown === 'timesheets'"
                  class="absolute top-full left-0 mt-1 w-56 bg-white rounded-md shadow-lg border border-gray-200 z-60"
                >
                  <div class="py-1">
                    <router-link
                      to="/timesheets/entry"
                      class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                    >
                      <PlusCircle class="w-4 h-4 mr-3" /> Entry & Management
                    </router-link>
                    <router-link
                      to="/timesheets/daily"
                      class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                    >
                      <Calendar class="w-4 h-4 mr-3" /> Daily Overview
                    </router-link>
                    <router-link
                      to="/timesheets/weekly"
                      class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                    >
                      <BarChart3 class="w-4 h-4 mr-3" /> Weekly Overview
                    </router-link>
                  </div>
                </div>
              </Transition>
            </div>
          </div>

          <router-link
            v-if="!userInfo.is_office_staff"
            to="/timesheets/my-time"
            class="flex items-center text-gray-700 hover:text-blue-600 transition-colors text-sm font-medium"
          >
            <Clock3 class="w-4 h-4 mr-1" /> My Time
          </router-link>

          <div class="relative" @click.stop v-if="userInfo.is_office_staff">
            <button
              @click="toggleDropdown('purchases')"
              class="flex items-center text-gray-700 hover:text-blue-600 transition-colors text-sm font-medium px-3 py-2 rounded-md duration-200"
            >
              <ShoppingCart class="w-4 h-4 mr-1" /> Purchases
              <ChevronDown class="ml-1 h-4 w-4" />
            </button>
            <Transition
              enter-active-class="transition-all duration-300 ease-out"
              enter-from-class="opacity-0 -translate-y-2 scale-95"
              enter-to-class="opacity-100 translate-y-0 scale-100"
              leave-active-class="transition-all duration-200 ease-in"
              leave-from-class="opacity-100 translate-y-0 scale-100"
              leave-to-class="opacity-0 -translate-y-2 scale-95"
            >
              <div
                v-if="activeDropdown === 'purchases'"
                class="absolute top-full left-0 mt-1 w-56 bg-white rounded-md shadow-lg border border-gray-200 z-[60]"
              >
                <RouterLink
                  to="/purchasing/po"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <FileText class="w-4 h-4 mr-2" /> Purchase Orders
                </RouterLink>
                <RouterLink
                  to="/purchasing/stock"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <Box class="w-4 h-4 mr-2" /> Use Stock
                </RouterLink>
                <RouterLink
                  to="/purchasing/pricing"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <UploadCloud class="w-4 h-4 mr-2" /> Upload Supplier Pricing
                </RouterLink>
                <RouterLink
                  to="/purchasing/mappings"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <FileText class="w-4 h-4 mr-2" /> Product Mappings
                </RouterLink>
              </div>
            </Transition>
          </div>

          <div class="relative" @click.stop v-if="userInfo.is_office_staff">
            <button
              @click="toggleDropdown('process')"
              class="flex items-center text-gray-700 hover:text-blue-600 transition-colors text-sm font-medium px-3 py-2 rounded-md duration-200"
            >
              <ShieldCheck class="w-4 h-4 mr-1" /> Process
              <ChevronDown class="ml-1 h-4 w-4" />
            </button>
            <Transition
              enter-active-class="transition-all duration-300 ease-out"
              enter-from-class="opacity-0 -translate-y-2 scale-95"
              enter-to-class="opacity-100 translate-y-0 scale-100"
              leave-active-class="transition-all duration-200 ease-in"
              leave-from-class="opacity-100 translate-y-0 scale-100"
              leave-to-class="opacity-0 -translate-y-2 scale-95"
            >
              <div
                v-if="activeDropdown === 'process'"
                class="absolute top-full left-0 mt-1 w-56 bg-white rounded-md shadow-lg border border-gray-200 z-[60]"
              >
                <div
                  class="px-4 py-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  Forms
                </div>
                <RouterLink
                  v-for="cat in processDocsStore.categories.forms"
                  :key="'form-' + cat"
                  :to="`/process-documents/forms/${cat}`"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all capitalize"
                >
                  <ClipboardList class="w-4 h-4 mr-2" /> {{ cat }}
                </RouterLink>
                <div class="border-t border-gray-200 my-1"></div>
                <div
                  class="px-4 py-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  Procedures
                </div>
                <RouterLink
                  v-for="cat in processDocsStore.categories.procedures"
                  :key="'proc-' + cat"
                  :to="`/process-documents/procedures/${cat}`"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all capitalize"
                >
                  <FileText class="w-4 h-4 mr-2" /> {{ cat }}
                </RouterLink>
                <div class="border-t border-gray-200 my-1"></div>
                <a
                  href="/manual/"
                  target="_blank"
                  @click="activeDropdown = null"
                  class="w-full flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-gray-50 font-medium transition-all"
                >
                  <GraduationCap class="w-4 h-4 mr-2" /> App Training
                </a>
              </div>
            </Transition>
          </div>

          <div class="relative" @click.stop v-if="userInfo.is_office_staff">
            <button
              @click="toggleDropdown('reports')"
              class="flex items-center text-gray-700 hover:text-blue-600 transition-colors text-sm font-medium px-3 py-2 rounded-md duration-200"
            >
              <BarChart3 class="w-4 h-4 mr-1" /> Reports
              <ChevronDown class="ml-1 h-4 w-4" />
            </button>
            <Transition
              enter-active-class="transition-all duration-300 ease-out"
              enter-from-class="opacity-0 -translate-y-2 scale-95"
              enter-to-class="opacity-100 translate-y-0 scale-100"
              leave-active-class="transition-all duration-200 ease-in"
              leave-from-class="opacity-100 translate-y-0 scale-100"
              leave-to-class="opacity-0 -translate-y-2 scale-95"
            >
              <div
                v-if="activeDropdown === 'reports'"
                class="absolute top-full left-0 mt-1 w-56 bg-white rounded-md shadow-lg border border-gray-200 z-[60]"
              >
                <div
                  class="px-4 py-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  CRM
                </div>
                <router-link
                  to="/reports/clients"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <Users class="w-4 h-4 mr-2" /> Clients
                </router-link>
                <div class="border-t border-gray-200 my-1"></div>
                <div
                  class="px-4 py-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  Management
                </div>
                <router-link
                  to="/reports/job-aging"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <Clock class="w-4 h-4 mr-2" /> Job Aging
                </router-link>
                <router-link
                  to="/reports/job-movement"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <TrendingUp class="w-4 h-4 mr-2" /> Job Movement
                </router-link>
                <router-link
                  to="/reports/job-profitability"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <DollarSign class="w-4 h-4 mr-2" /> Job Profitability
                </router-link>
                <router-link
                  to="/reports/kpi"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <BarChart3 class="w-4 h-4 mr-2" /> KPI Reports
                </router-link>
                <router-link
                  to="/reports/rdti-spend"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <FlaskConical class="w-4 h-4 mr-2" /> RDTI Spend
                </router-link>
                <router-link
                  to="/reports/sales-forecast"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <TrendingUp class="w-4 h-4 mr-2" /> Sales Forecast
                </router-link>
                <router-link
                  to="/reports/staff-performance"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <Users class="w-4 h-4 mr-2" /> Staff Performance
                </router-link>
                <div class="border-t border-gray-200 my-1"></div>
                <div
                  class="px-4 py-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  Reconciliation
                </div>
                <router-link
                  to="/reports/payroll-reconciliation"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <Scale class="w-4 h-4 mr-2" /> Payroll (Xero)
                </router-link>
                <router-link
                  to="/reports/profit-and-loss"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <FileText class="w-4 h-4 mr-2" /> Profit & Loss (Xero)
                </router-link>
                <div class="border-t border-gray-200 my-1"></div>
                <div
                  class="px-4 py-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  Data Quality
                </div>
                <router-link
                  to="/reports/data-quality/archived-jobs"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <AlertTriangle class="w-4 h-4 mr-2" /> Archived Jobs Validation
                </router-link>
              </div>
            </Transition>
          </div>

          <div class="relative" @click.stop v-if="userInfo.is_office_staff">
            <button
              @click="toggleDropdown('admin')"
              class="flex items-center text-gray-700 hover:text-blue-600 transition-colors text-sm font-medium px-3 py-2 rounded-md duration-200"
            >
              <Settings class="w-4 h-4 mr-1" /> Admin
              <ChevronDown class="ml-1 h-4 w-4" />
            </button>
            <Transition
              enter-active-class="transition-all duration-300 ease-out"
              enter-from-class="opacity-0 -translate-y-2 scale-95"
              enter-to-class="opacity-100 translate-y-0 scale-100"
              leave-active-class="transition-all duration-200 ease-in"
              leave-from-class="opacity-100 translate-y-0 scale-100"
              leave-to-class="opacity-0 -translate-y-2 scale-95"
            >
              <div
                v-if="activeDropdown === 'admin'"
                class="absolute top-full left-0 mt-1 w-56 bg-white rounded-md shadow-lg border border-gray-200 z-[60]"
              >
                <router-link
                  to="/xero"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <Link2 class="w-4 h-4 mr-2" /> Xero
                </router-link>
                <div class="border-t border-gray-200 my-1"></div>
                <router-link
                  v-for="page in adminPages"
                  :key="page.key"
                  :to="`/admin/${page.key}`"
                  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                >
                  <component :is="page.icon" class="w-4 h-4 mr-2" /> {{ page.label }}
                </router-link>
                <template v-if="adminExternalLinks.length">
                  <div class="border-t border-gray-200 my-1"></div>
                  <a
                    v-for="link in adminExternalLinks"
                    :key="link.key"
                    :href="link.externalUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
                  >
                    <component :is="link.icon" class="w-4 h-4 mr-2" /> {{ link.label }}
                  </a>
                </template>
              </div>
            </Transition>
          </div>
        </div>
      </div>

      <div class="flex items-center space-x-2">
        <div class="relative">
          <Search
            class="absolute left-2.5 top-1/2 transform -translate-y-1/2 h-3.5 w-3.5 text-gray-400"
          />
          <input
            v-model="searchInput"
            type="text"
            placeholder="Search jobs..."
            class="w-36 sm:w-48 lg:w-64 pl-8 pr-3 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            @keydown.enter="submitSearch"
          />
        </div>
        <button
          @click="openAdvancedSearch"
          class="hidden sm:flex px-2 py-1.5 bg-blue-500 hover:bg-blue-600 text-white text-xs rounded-md transition-all duration-200 items-center flex-shrink-0"
        >
          <SlidersHorizontal class="h-3.5 w-3.5 lg:mr-1" />
          <span class="hidden lg:inline">Advanced</span>
        </button>
      </div>

      <div class="flex items-center space-x-3">
        <WorkshopOfficeToggle />

        <div class="hidden md:flex lg:hidden items-center space-x-2">
          <span class="text-gray-700 text-xs">{{ userInfo.displayName?.split(' ')[0] }}</span>
          <button
            @click="handleLogout"
            class="bg-red-500 hover:bg-red-600 text-white px-2 py-0.5 rounded text-xs transition-colors"
          >
            Logout
          </button>
        </div>

        <div class="hidden lg:flex items-center space-x-4">
          <span class="text-gray-700 text-sm">Welcome, {{ userInfo.displayName }}!</span>
          <button
            @click="handleLogout"
            class="bg-red-500 hover:bg-red-600 text-white px-3 py-1.5 rounded-md transition-colors text-sm"
          >
            Log out
          </button>
        </div>

        <div class="flex md:hidden items-center">
          <span class="text-gray-700 text-xs mr-2">{{ userInfo.displayName?.split(' ')[0] }}</span>
          <button
            @click="handleLogout"
            class="bg-red-500 hover:bg-red-600 text-white px-2 py-1 rounded text-xs"
          >
            Logout
          </button>
        </div>
      </div>
    </div>

    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 transform -translate-y-2"
      enter-to-class="opacity-100 transform translate-y-0"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100 transform translate-y-0"
      leave-to-class="opacity-0 transform -translate-y-2"
    >
      <div
        v-if="showMobileMenu"
        class="lg:hidden absolute top-full left-0 right-0 bg-white border-b border-gray-200 shadow-lg z-[60]"
      >
        <div class="px-4 py-4 max-h-[70vh] overflow-y-auto">
          <div class="grid grid-cols-1 gap-3">
            <div class="space-y-3">
              <router-link
                :to="kanbanNav.to"
                class="flex items-center px-3 py-2 text-gray-700 hover:text-blue-600 hover:bg-blue-50 rounded-md transition-all"
                @click="closeMobileMenu"
              >
                <Kanban class="w-4 h-4 mr-2" /> {{ kanbanNav.label }}
              </router-link>
              <router-link
                v-if="isOfficeStaff"
                to="/jobs/create"
                class="flex items-center px-3 py-2 text-gray-700 hover:text-blue-600 hover:bg-blue-50 rounded-md transition-all"
                data-automation-id="AppNavbar-create-job-mobile"
                @click="closeMobileMenu"
              >
                <FilePlus class="w-4 h-4 mr-2" /> Create Job
              </router-link>
              <div class="bg-gray-50 rounded-md" v-if="isOfficeStaff">
                <button
                  @click="toggleMobileSection('timesheets')"
                  class="w-full flex items-center justify-between px-3 py-2 text-gray-700 hover:text-blue-600 transition-colors font-medium"
                >
                  <span class="flex items-center space-x-2">
                    <Calendar class="w-4 h-4" />
                    <span>Timesheets</span>
                  </span>
                  <ChevronDown
                    :class="[
                      'h-4 w-4 transition-transform duration-200',
                      mobileSections.timesheets ? 'rotate-180' : '',
                    ]"
                  />
                </button>
                <Transition
                  enter-active-class="transition-all duration-200 ease-out"
                  enter-from-class="opacity-0 max-h-0"
                  enter-to-class="opacity-100 max-h-40"
                  leave-active-class="transition-all duration-200 ease-in"
                  leave-from-class="opacity-100 max-h-40"
                  leave-to-class="opacity-0 max-h-0"
                >
                  <div v-if="mobileSections.timesheets" class="overflow-hidden">
                    <div class="px-3 pb-2 space-y-1">
                      <router-link
                        to="/timesheets/entry"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <PlusCircle class="w-4 h-4 mr-2" /> Entry & Management
                      </router-link>
                      <router-link
                        to="/timesheets/daily"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <Calendar class="w-4 h-4 mr-2" /> Daily Overview
                      </router-link>
                      <router-link
                        to="/timesheets/weekly"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <BarChart3 class="w-4 h-4 mr-2" /> Weekly Overview
                      </router-link>
                    </div>
                  </div>
                </Transition>
              </div>
              <router-link
                v-if="!isOfficeStaff"
                to="/timesheets/my-time"
                class="flex items-center space-x-2 w-full px-3 py-2 text-gray-700 hover:text-blue-600 hover:bg-blue-50 rounded-md transition-all"
                @click="closeMobileMenu"
              >
                <Clock3 class="w-4 h-4" />
                <span>My Time</span>
              </router-link>
            </div>

            <div class="border-t border-gray-200" v-if="userInfo.is_office_staff"></div>

            <div class="space-y-2">
              <div class="bg-gray-50 rounded-md" v-if="isOfficeStaff">
                <button
                  @click="toggleMobileSection('purchases')"
                  class="w-full flex items-center justify-between px-3 py-2 text-gray-700 hover:text-blue-600 transition-colors font-medium"
                >
                  <span class="flex items-center space-x-2">
                    <ShoppingCart class="w-4 h-4" />
                    <span>Purchases</span>
                  </span>
                  <ChevronDown
                    :class="[
                      'h-4 w-4 transition-transform duration-200',
                      mobileSections.purchases ? 'rotate-180' : '',
                    ]"
                  />
                </button>
                <Transition
                  enter-active-class="transition-all duration-200 ease-out"
                  enter-from-class="opacity-0 max-h-0"
                  enter-to-class="opacity-100 max-h-40"
                  leave-active-class="transition-all duration-200 ease-in"
                  leave-from-class="opacity-100 max-h-40"
                  leave-to-class="opacity-0 max-h-0"
                >
                  <div v-if="mobileSections.purchases" class="overflow-hidden">
                    <div class="px-3 pb-2 space-y-1">
                      <RouterLink
                        to="/purchasing/po"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <FileText class="w-4 h-4 mr-2" /> Purchase Orders
                      </RouterLink>
                      <RouterLink
                        to="/purchasing/stock"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <Box class="w-4 h-4 mr-2" /> Use Stock
                      </RouterLink>
                      <RouterLink
                        to="/purchasing/pricing"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <UploadCloud class="w-4 h-4 mr-2" /> Upload Supplier Pricing
                      </RouterLink>
                      <RouterLink
                        to="/purchasing/mappings"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <FileText class="w-4 h-4 mr-2" /> Product Mappings
                      </RouterLink>
                    </div>
                  </div>
                </Transition>
              </div>

              <div class="bg-gray-50 rounded-md" v-if="isOfficeStaff">
                <button
                  @click="toggleMobileSection('process')"
                  class="w-full flex items-center justify-between px-3 py-2 text-gray-700 hover:text-blue-600 transition-colors font-medium"
                >
                  <span class="flex items-center space-x-2">
                    <ShieldCheck class="w-4 h-4" />
                    <span>Process</span>
                  </span>
                  <ChevronDown
                    :class="[
                      'h-4 w-4 transition-transform duration-200',
                      mobileSections.process ? 'rotate-180' : '',
                    ]"
                  />
                </button>
                <Transition
                  enter-active-class="transition-all duration-200 ease-out"
                  enter-from-class="opacity-0 max-h-0"
                  enter-to-class="opacity-100 max-h-40"
                  leave-active-class="transition-all duration-200 ease-in"
                  leave-from-class="opacity-100 max-h-40"
                  leave-to-class="opacity-0 max-h-0"
                >
                  <div v-if="mobileSections.process" class="overflow-hidden">
                    <div class="px-3 pb-2 space-y-1">
                      <div
                        class="px-2 py-1 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                      >
                        Forms
                      </div>
                      <RouterLink
                        v-for="cat in processDocsStore.categories.forms"
                        :key="'form-' + cat"
                        :to="`/process-documents/forms/${cat}`"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all capitalize"
                        @click="closeMobileMenu"
                      >
                        <ClipboardList class="w-4 h-4 mr-2" /> {{ cat }}
                      </RouterLink>
                      <div class="border-t border-gray-200 my-1"></div>
                      <div
                        class="px-2 py-1 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                      >
                        Procedures
                      </div>
                      <RouterLink
                        v-for="cat in processDocsStore.categories.procedures"
                        :key="'proc-' + cat"
                        :to="`/process-documents/procedures/${cat}`"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all capitalize"
                        @click="closeMobileMenu"
                      >
                        <FileText class="w-4 h-4 mr-2" /> {{ cat }}
                      </RouterLink>
                      <div class="border-t border-gray-200 my-1"></div>
                      <a
                        href="/manual/"
                        target="_blank"
                        @click="closeMobileMenu()"
                        class="flex items-center w-full text-left px-2 py-1.5 text-sm text-gray-700 hover:text-blue-600 hover:bg-gray-50 rounded transition-all"
                      >
                        <GraduationCap class="w-4 h-4 mr-2" /> App Training
                      </a>
                    </div>
                  </div>
                </Transition>
              </div>

              <div class="bg-gray-50 rounded-md" v-if="isOfficeStaff">
                <button
                  @click="toggleMobileSection('reports')"
                  class="w-full flex items-center justify-between px-3 py-2 text-gray-700 hover:text-blue-600 transition-colors font-medium"
                >
                  <span class="flex items-center space-x-2">
                    <BarChart3 class="w-4 h-4" />
                    <span>Reports</span>
                  </span>
                  <ChevronDown
                    :class="[
                      'h-4 w-4 transition-transform duration-200',
                      mobileSections.reports ? 'rotate-180' : '',
                    ]"
                  />
                </button>
                <Transition
                  enter-active-class="transition-all duration-200 ease-out"
                  enter-from-class="opacity-0 max-h-0"
                  enter-to-class="opacity-100 max-h-40"
                  leave-active-class="transition-all duration-200 ease-in"
                  leave-from-class="opacity-100 max-h-40"
                  leave-to-class="opacity-0 max-h-0"
                >
                  <div v-if="mobileSections.reports" class="overflow-hidden">
                    <div class="px-3 pb-2 space-y-1">
                      <div
                        class="px-2 py-1 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                      >
                        CRM
                      </div>
                      <router-link
                        to="/reports/clients"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <Users class="w-4 h-4 mr-2" /> Clients
                      </router-link>
                      <div class="border-t border-gray-200 mt-2 mb-1"></div>
                      <div
                        class="px-2 py-1 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                      >
                        Management
                      </div>
                      <router-link
                        to="/reports/job-aging"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <Clock class="w-4 h-4 mr-2" /> Job Aging
                      </router-link>
                      <router-link
                        to="/reports/job-movement"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <TrendingUp class="w-4 h-4 mr-2" /> Job Movement
                      </router-link>
                      <router-link
                        to="/reports/job-profitability"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <DollarSign class="w-4 h-4 mr-2" /> Job Profitability
                      </router-link>
                      <router-link
                        to="/reports/kpi"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <BarChart3 class="w-4 h-4 mr-2" /> KPI Reports
                      </router-link>
                      <router-link
                        to="/reports/rdti-spend"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <FlaskConical class="w-4 h-4 mr-2" /> RDTI Spend
                      </router-link>
                      <router-link
                        to="/reports/sales-forecast"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <TrendingUp class="w-4 h-4 mr-2" /> Sales Forecast
                      </router-link>
                      <router-link
                        to="/reports/staff-performance"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <Users class="w-4 h-4 mr-2" /> Staff Performance
                      </router-link>
                      <div class="border-t border-gray-200 mt-2 mb-1"></div>
                      <div
                        class="px-2 py-1 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                      >
                        Reconciliation
                      </div>
                      <router-link
                        to="/reports/payroll-reconciliation"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <Scale class="w-4 h-4 mr-2" /> Payroll (Xero)
                      </router-link>
                      <router-link
                        to="/reports/profit-and-loss"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <FileText class="w-4 h-4 mr-2" /> Profit & Loss (Xero)
                      </router-link>
                      <div class="border-t border-gray-200 mt-2 mb-1"></div>
                      <div
                        class="px-2 py-1 text-xs font-semibold text-gray-500 uppercase tracking-wider"
                      >
                        Data Quality
                      </div>
                      <router-link
                        to="/reports/data-quality/archived-jobs"
                        class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
                        @click="closeMobileMenu"
                      >
                        <AlertTriangle class="w-4 h-4 mr-2" /> Archived Jobs Validation
                      </router-link>
                    </div>
                  </div>
                </Transition>
              </div>

              <div class="bg-gray-50 rounded-md" v-if="userInfo.is_superuser">
                <button
                  @click="toggleMobileSection('admin')"
                  class="w-full flex items-center justify-between px-3 py-2 text-gray-700 hover:text-blue-600 transition-colors font-medium"
                >
                  <span class="flex items-center space-x-2">
                    <Settings class="w-4 h-4" />
                    <span>Admin</span>
                  </span>
                  <ChevronDown :class="[mobileSections.admin ? 'rotate-180' : '']" />
                </button>
                <Transition
                  enter-active-class="transition-all duration-200 ease-out"
                  enter-from-class="opacity-0 max-h-0"
                  enter-to-class="opacity-100 max-h-40"
                  leave-active-class="transition-all duration-200 ease-in"
                  leave-to-class="opacity-0 max-h-0"
                >
                  <div v-if="mobileSections.admin" class="overflow-hidden">
                    <router-link
                      to="/xero"
                      class="flex items-center px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                      @click="closeMobileMenu"
                    >
                      <Link2 class="w-4 h-4 mr-2" /> Xero
                    </router-link>
                    <div class="border-t border-gray-200 my-1 mx-2"></div>
                    <router-link
                      v-for="page in adminPages"
                      :key="page.key"
                      :to="`/admin/${page.key}`"
                      class="flex items-center px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                      @click="closeMobileMenu"
                    >
                      <component :is="page.icon" class="w-4 h-4 mr-2" /> {{ page.label }}
                    </router-link>
                    <template v-if="adminExternalLinks.length">
                      <div class="border-t border-gray-200 my-1 mx-2"></div>
                      <a
                        v-for="link in adminExternalLinks"
                        :key="link.key"
                        :href="link.externalUrl"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="flex items-center px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                        @click="closeMobileMenu"
                      >
                        <component :is="link.icon" class="w-4 h-4 mr-2" /> {{ link.label }}
                      </a>
                    </template>
                  </div>
                </Transition>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </nav>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import { useRouter, useRoute } from 'vue-router'
import {
  ChevronDown,
  Menu,
  X,
  Calendar,
  PlusCircle,
  BarChart3,
  Search,
  SlidersHorizontal,
  Kanban,
  FilePlus,
  ShoppingCart,
  FileText,
  Box,
  UploadCloud,
  Link2,
  Settings,
  Clock,
  AlertTriangle,
  TrendingUp,
  ShieldCheck,
  ClipboardList,
  GraduationCap,
  Clock3,
  Users,
  DollarSign,
  Scale,
  FlaskConical,
} from 'lucide-vue-next'
import { useAppLayout } from '@/composables/useAppLayout'
import { adminPages, adminExternalLinks } from '@/config/adminPages'
import { useProcessDocumentsStore } from '@/stores/processDocuments'
import WorkshopOfficeToggle from '@/components/board/WorkshopOfficeToggle.vue'

const router = useRouter()
const route = useRoute()
const searchInput = ref((route.query.q as string) || '')

const submitSearch = () => {
  const q = searchInput.value.trim()
  if (route.path === '/kanban') {
    router.replace({ path: '/kanban', query: q ? { q } : {} })
  } else {
    router.push({ path: '/kanban', query: q ? { q } : {} })
  }
}

const debouncedSubmitSearch = useDebounceFn(() => {
  if (route.path === '/kanban') {
    submitSearch()
  }
}, 300)

watch(searchInput, () => {
  debouncedSubmitSearch()
})

const openAdvancedSearch = () => {
  const query: Record<string, string> = { advanced: '1' }
  const q = (route.query.q as string) || searchInput.value.trim()
  if (q) query.q = q
  if (route.path === '/kanban') {
    router.replace({ path: '/kanban', query })
  } else {
    router.push({ path: '/kanban', query })
  }
}

watch(
  () => route.query.q,
  (newQ) => {
    searchInput.value = (newQ as string) || ''
  },
)

const activeDropdown = ref<string | null>(null)
const showMobileMenu = ref(false)
type MobileSection = 'timesheets' | 'purchases' | 'process' | 'reports' | 'admin'
const mobileSections = ref<Record<MobileSection, boolean>>({
  timesheets: false,
  purchases: false,
  process: false,
  reports: false,
  admin: false,
})

const { userInfo, handleLogout } = useAppLayout()
const isOfficeStaff = computed(() => !!userInfo.value?.is_office_staff)

const processDocsStore = useProcessDocumentsStore()

const kanbanNav = computed(() =>
  isOfficeStaff.value
    ? { label: 'Kanban Board', to: '/kanban' }
    : { label: 'Kanban Board', to: '/kanban' },
)

const toggleDropdown = (dropdown: string) => {
  activeDropdown.value = activeDropdown.value === dropdown ? null : dropdown
}

const toggleMobileMenu = () => {
  showMobileMenu.value = !showMobileMenu.value
  if (!showMobileMenu.value) {
    mobileSections.value = {
      timesheets: false,
      purchases: false,
      process: false,
      reports: false,
      admin: false,
    }
  }
}

const closeMobileMenu = () => {
  showMobileMenu.value = false
  mobileSections.value = {
    timesheets: false,
    purchases: false,
    process: false,
    reports: false,
    admin: false,
  }
}

const toggleMobileSection = (section: MobileSection) => {
  mobileSections.value[section] = !mobileSections.value[section]
}

let clickHandler: ((e: MouseEvent) => void) | null = null

onMounted(() => {
  clickHandler = (e: MouseEvent) => {
    const dropdowns = document.querySelectorAll('.absolute, .z-60')
    let insideDropdown = false
    dropdowns.forEach((el) => {
      if (el.contains(e.target as Node)) insideDropdown = true
    })
    if (!insideDropdown) activeDropdown.value = null
  }
  document.addEventListener('click', clickHandler)

  processDocsStore.loadCategories()
})

onUnmounted(() => {
  if (clickHandler) document.removeEventListener('click', clickHandler)
})
</script>
